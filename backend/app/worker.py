"""Background worker: polls due streams, runs a durable summary, then classifies a batch."""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import get_settings
from .db import init_db, session_scope
from .models import SourceProfile
from .model_settings import purpose_configured
from .pipeline.classify import enrich_pending
from .pipeline.ingest import is_due, run_profile
from .pipeline.summarize import next_pending_ids, run_summary
from .worker_health import WorkerMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def tick(monitor=None) -> None:
    def report(phase, **fields):
        if monitor:
            monitor.report(phase, **fields)

    now = datetime.now(timezone.utc)
    report("ingesting", summary_id=None)
    with session_scope() as s:
        ids = [p.id for p in s.scalars(select(SourceProfile)).all() if is_due(p, now)]
    for pid in ids:  # one transaction per profile so a failure doesn't roll back the others
        with session_scope() as s:
            run_profile(s, s.get(SourceProfile, pid))

    st = get_settings()
    with session_scope() as s:
        summary_ready = purpose_configured(s, 'summary', st)
        classify_ready = purpose_configured(s, 'classify', st)
    if not (summary_ready or classify_ready):
        log.warning('Selected model providers are not configured; articles and summaries stay pending')
        return
    # Bound classification work so a continuous backlog cannot starve summaries/polls.
    report("summarising")
    try:
        for sid in (next_pending_ids() if summary_ready else []):
            report("summarising", summary_id=sid)
            if run_summary(sid):
                break  # one summary per tick, oldest first
    finally:
        report("classifying", summary_id=None)
    if classify_ready:
        with session_scope() as s:
            enrich_pending(s)


def main() -> None:
    init_db()
    st = get_settings()
    log.info("worker started; tick every %ss", st.worker_tick_seconds)
    monitor = WorkerMonitor()
    monitor.start()
    try:
        while True:
            started = time.monotonic()
            try:
                tick(monitor)
                monitor.report("idle", last_tick_at=datetime.now(timezone.utc), last_error=None, summary_id=None)
            except Exception as e:  # keep the loop alive; expose the failure independently of logs
                log.exception("tick failed")
                monitor.report("error", last_error=str(e)[:1000], summary_id=None)
            time.sleep(max(5, st.worker_tick_seconds - (time.monotonic() - started)))
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()

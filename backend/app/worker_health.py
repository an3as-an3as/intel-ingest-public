"""Independent heartbeat: remains fresh during ingestion and model calls."""
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from .db import session_scope
from .models import Article, Summary, WorkerState

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 45


def utcnow():
    return datetime.now(timezone.utc)


class WorkerMonitor:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.fields = dict(phase="starting", phase_started_at=utcnow(), last_tick_at=None,
                           last_error=None, summary_id=None)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="worker-heartbeat", daemon=True)

    def report(self, phase=None, **fields):
        with self.lock:
            if phase is not None:
                fields.update(phase=phase, phase_started_at=utcnow())
            self.fields.update(fields)
            try:
                with session_scope() as s:
                    row = s.get(WorkerState, self.id)
                    if row is None:
                        row = WorkerState(id=self.id)
                        s.add(row)
                    for key, value in self.fields.items():
                        setattr(row, key, value)
                    row.heartbeat_at = utcnow()
            except Exception:
                log.exception("could not publish worker heartbeat")

    def start(self):
        # Keep recent crash history without accumulating rows indefinitely.
        with session_scope() as s:
            s.execute(delete(WorkerState).where(WorkerState.heartbeat_at < utcnow() - timedelta(days=7)))
        self.report()
        self.thread.start()

    def _loop(self):
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            self.report()

    def stop(self):
        self.stop_event.set()
        self.thread.join()
        self.report("stopped", summary_id=None)


def pipeline_health(s, at):
    workers = s.scalars(select(WorkerState).order_by(WorkerState.heartbeat_at.desc())).all()
    pending_since = s.scalar(select(func.min(Article.ingested_at)).where(Article.status == "pending"))
    summary_since = s.scalar(select(func.min(Summary.created_at)).where(Summary.status == "pending"))
    summary_counts = dict(s.execute(select(Summary.status, func.count()).group_by(Summary.status)).all())
    return {
        "workers": [{
            "id": w.id, "heartbeat_at": w.heartbeat_at.isoformat(),
            "healthy": (at - w.heartbeat_at).total_seconds() <= STALE_SECONDS and w.phase != "stopped",
            "phase": w.phase, "phase_started_at": w.phase_started_at.isoformat(),
            "last_tick_at": w.last_tick_at.isoformat() if w.last_tick_at else None,
            "last_error": w.last_error, "summary_id": w.summary_id,
        } for w in workers],
        "oldest_pending_ingested_at": pending_since.isoformat() if pending_since else None,
        "oldest_pending_summary_at": summary_since.isoformat() if summary_since else None,
        "summaries_by_status": summary_counts,
        "classified_24h": s.scalar(select(func.count()).select_from(Article).where(
            Article.enriched_at >= at - timedelta(hours=24))),
    }

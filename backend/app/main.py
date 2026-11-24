import base64
import hashlib
import math
import re
import secrets
import anthropic
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, model_validator
from typing import Literal
from sqlalchemy import Text, and_, cast, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from . import model_settings, model_providers, branding
from .dashboard_setup import DashboardSetupIn, compile_dashboard
from .pipeline.classify import build_system_prompt
from .db import get_db, init_db
from .models import Article, ArticlePir, IngestRun, IngestRunArticle, KeywordTranslationReview, Pir, PirSet, ProfileDashboard, SourceProfile, Summary
from .pipeline.ingest import next_poll_at, request_poll
from .pipeline.catchup import CatchUpPreviewIn, preview_catchup
from .pipeline.analytics import parse_window, pir_stats, set_activity, set_article_conditions
from .pipeline.export_summary import report_export
from .pipeline.summarize import period_bounds
from .worker_health import pipeline_health
from .sources.gdelt import build_query as gdelt_query
from .sources.newscatcher import build_requests as newscatcher_requests, build_q as newscatcher_query, query_budget, query_planner_version, request_credit_estimate, NEWS_API, V3_API
from .sources.event_vocabulary import summary as vocabulary_summary
from .sources.content_matching import settings as content_matching_settings
from .sources import keyword_translation
from .sources.newscatcher_filters import filter_metadata, validate_native_filters
from .sources.options import COUNTRIES, EVENT_QUERIES, ingestion_options
from .pipeline.scope import dashboard_scope, profile_scope
from .taxonomy import EVENT_TYPE_LABELS, REGION_LABELS

_here = Path(__file__).resolve().parent
# /app/frontend inside Docker, ../frontend when run from a checkout
FRONTEND = next((d for d in (_here.parent / "frontend", _here.parent.parent / "frontend") if d.is_dir()),
                _here.parent / "frontend")

# Fingerprint the whole frontend so a deployment refreshes transitive module imports too.
UI_VERSION = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(FRONTEND.iterdir())
                                   if p.suffix in {'.html', '.js', '.css'})).hexdigest()[:16]

app = FastAPI(title="Intel Ingest")


@app.middleware('http')
async def frontend_cache_policy(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['X-UI-Version'] = UI_VERSION
    return response


@app.on_event("startup")
def _startup():
    init_db()


# ---------- optional shared password (HTTP Basic, any username) ----------
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    pw = get_settings().app_password
    if pw and request.url.path != "/healthz":
        ok = False
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                _, _, given = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(given, pw)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="intel-ingest"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- serialisers ----------------
def ser_article(a: Article) -> dict:
    return {
        "id": a.id, "url": a.url, "title": a.title, "summary": a.ai_summary or a.description,
        "source_domain": a.source_domain, "source_country": a.source_country, "language": a.language,
        "image_url": a.image_url, "published_at": a.published_at.isoformat(), "status": a.status,
        "event_type": a.event_type, "region": a.region, "countries": a.countries or [],
        "location_name": a.location_name, "lat": a.lat, "lon": a.lon, "geo_precision": a.geo_precision,
        "profile_id": a.profile_id, "error": a.error,
        "pirs": [{"pir_id": m.pir_id, "code": m.pir.code, "score": round(m.score, 2), "rationale": m.rationale}
                 for m in sorted(a.matches, key=lambda m: -m.score)],
    }


def ser_pir(p: Pir) -> dict:
    return {"id": p.id, "set_id": p.set_id, "code": p.code, "title": p.title, "question": p.question,
            "indicators": p.indicators, "priority": p.priority, "active": p.active}


def ser_set(ps: PirSet) -> dict:
    return {"id": ps.id, "name": ps.name, "description": ps.description, "pirs": [ser_pir(p) for p in ps.pirs]}


def ser_profile(p: SourceProfile) -> dict:
    state, due = p.ingest_state, next_poll_at(p)
    def iso(value):
        return value.isoformat() if value else None
    return {"id": p.id, "name": p.name, "source": p.source, "params": p.params, "enabled": p.enabled,
            "interval_minutes": p.interval_minutes, "last_status": p.last_status,
            "dashboard_ids": [link.set_id for link in p.dashboard_links],
            "next_run_at": iso(due), "last_run_at": iso(p.last_run_at),
            "ingestion": {"last_attempt_at": iso(state.last_attempt_at) if state else None,
                          "last_success_at": iso(state.last_success_at if state else p.last_run_at),
                          "retry_at": iso(state.retry_at) if state else None,
                          "failures": state.failures if state else 0,
                          "queued": bool(state and state.run_requested)}}


def ser_summary(x: Summary, full=False) -> dict:
    d = {"id": x.id, "set_id": x.set_id, "period_label": x.period_label, "status": x.status,
         "period_start": x.period_start.isoformat(), "period_end": x.period_end.isoformat(),
         "article_count": x.article_count, "model": x.model, "error": x.error,
         "created_at": x.created_at.isoformat()}
    if full:
        d.update(content=x.content, references=x.references or {})
    return d


# ---------------- meta & status ----------------
@app.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    st = get_settings()
    models = model_settings.settings_response(db)['effective']
    return {"environment": st.app_environment, "event_types": EVENT_TYPE_LABELS, "regions": REGION_LABELS,
            "map": {"tile_url": st.map_tile_url, "attribution": st.map_tile_attribution},
            "ingestion_options": ingestion_options(), "newscatcher_filters": filter_metadata(),
            "sources": ["gdelt", "newscatcher"], "newscatcher_configured": bool(st.newscatcher_api_key),
            "claude_configured": bool(st.anthropic_api_key),
            "classify_configured": models['classify']['configured'],
            "summary_configured": models['summary']['configured'],
            "models": {"classify": models['classify']['model'], "summary": models['summary']['model']},
            "branding": branding.public(db)}


# ---------------- branding (shared logo) ----------------
@app.get('/api/branding')
def get_branding(db: Session = Depends(get_db)):
    return branding.public(db)


@app.get('/api/branding/logo')
def get_logo(db: Session = Depends(get_db)):
    found = branding.logo(db) or _404()
    data, mime = found
    return Response(data, media_type=mime, headers={
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-cache',
        'Content-Security-Policy': "default-src 'none'; sandbox",
        'Content-Disposition': 'inline; filename="logo"'})


@app.put('/api/branding/logo')
def put_logo(body: branding.LogoIn, db: Session = Depends(get_db)):
    try:
        return branding.save_logo(db, body.data_url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put('/api/branding/name')
def put_name(body: branding.NameIn, db: Session = Depends(get_db)):
    return branding.save_name(db, body)


@app.delete('/api/branding/name')
def delete_name(db: Session = Depends(get_db)):
    return branding.reset_name(db)


@app.delete('/api/branding/logo')
def delete_logo(db: Session = Depends(get_db)):
    return branding.remove_logo(db)


@app.get('/api/settings/models')
def get_model_settings(db: Session = Depends(get_db)):
    return model_settings.settings_response(db)


@app.get('/api/models')
def list_models(provider_id: model_settings.Provider = Query('anthropic', alias='provider')):
    try:
        return {'provider':provider_id, 'models':model_settings.available_models(provider_id)}
    except (anthropic.APIError, model_providers.ProviderError):
        raise HTTPException(502, 'Could not load provider models. Check server configuration, permissions and connectivity.')


@app.put('/api/settings/models')
def update_model_settings(body: model_settings.ModelSettingsIn, db: Session = Depends(get_db)):
    try:
        return model_settings.save_settings(db, body)
    except (anthropic.APIError, model_providers.ProviderError):
        raise HTTPException(502, 'Could not verify the selected models. Check API key access, model IDs and connectivity. No changes saved.')


@app.delete('/api/settings/models')
def reset_model_settings(db: Session = Depends(get_db)):
    row = db.get(model_settings.AppSetting, model_settings.KEY)
    if row:
        db.delete(row)
    db.commit()
    return model_settings.settings_response(db)


@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Article.status, func.count()).group_by(Article.status)).all())
    last24 = db.scalar(select(func.count()).where(Article.ingested_at >= now() - timedelta(hours=24)))
    return {"articles_by_status": counts, "ingested_24h": last24, **pipeline_health(db, now()),
            "profiles": [ser_profile(p) for p in db.scalars(select(SourceProfile).order_by(SourceProfile.id))]}


class ReclassifyIn(BaseModel):
    days: int = Field(7, ge=1, le=90)
    include_irrelevant: bool = True


@app.post("/api/admin/reclassify")
def reclassify(body: ReclassifyIn, db: Session = Depends(get_db)):
    """Re-run classification (e.g. after editing PIRs) for recent articles."""
    statuses = ["enriched", "failed"] + (["irrelevant"] if body.include_irrelevant else [])
    r = db.execute(update(Article).where(Article.published_at >= now() - timedelta(days=body.days),
                                         Article.status.in_(statuses)).values(status="pending"))
    db.commit()
    return {"queued": r.rowcount}


@app.post("/api/admin/retry-failed")
def retry_failed(db: Session = Depends(get_db)):
    r = db.execute(update(Article).where(Article.status == "failed").values(status="pending"))
    db.commit()
    return {"queued": r.rowcount}


# ---------------- ingest profiles ----------------
class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: Literal["gdelt", "newscatcher"] = "newscatcher"
    params: dict = Field(default_factory=dict)
    enabled: bool = False
    interval_minutes: int = Field(30, ge=5, le=1440)
    dashboard_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_params(self, info: ValidationInfo):
        translation_draft = bool(info.context and info.context.get('translation_draft'))
        if not self.name.strip():
            raise ValueError("Name is required")
        for key in ("keywords", "exclude_keywords", "themes", "languages", "source_countries",
                    "coverage_countries", "coverage_regions", "event_presets"):
            values = self.params.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{key} must be a list of non-empty strings")
        for key, default, maximum in (("max_records", 100, 1000), ("lookback_hours", 24, 720)):
            value = self.params.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{key} must be between 1 and {maximum}")
        if self.source != 'newscatcher' and self.params.get('multilingual_enabled'):
            raise ValueError('Multilingual query expansion is currently supported only for NewsCatcher')
        if self.source != 'newscatcher' and self.params.get('content_matching', 'provider-default') != 'provider-default':
            raise ValueError('English translated-content matching is supported only for NewsCatcher Articles')
        if self.source == "newscatcher":
            keyword_translation.validate_flags(self.params, require_review=not translation_draft)
            content_matching_settings(self.params, self.params.get('endpoint', 'search'))
            if not isinstance(self.params.get('query', ''), str):
                raise ValueError('NewsCatcher query must be text')
            validate_native_filters(self.params)
            for key in ("source_countries", "coverage_countries"):
                if any(c not in COUNTRIES for c in self.params.get(key, [])):
                    raise ValueError(f"{key} requires ISO country codes")
            if any(e not in EVENT_QUERIES for e in self.params.get("event_presets", [])):
                raise ValueError("Unknown event preset")
            if any(len(l) != 2 or not l.isalpha() for l in self.params.get("languages", [])):
                raise ValueError("Languages require two-letter codes")
            for key in ('source_countries', 'languages'):
                if len(self.params.get(key, [])) > 100:
                    raise ValueError(f'NewsCatcher {key} accepts at most 100 values')
            if not self.params.get("keywords") and not self.params.get("event_presets") and not self.params.get('query', '').strip():
                raise ValueError("NewsCatcher needs keywords, an event preset or an advanced query")
            if translation_draft:
                # Validate source syntax/settings without compiling paid collection lanes.
                # The review's own row/language guards remain in create_review().
                query_budget(self.params)
                newscatcher_query(self.params)
            else:
                instant = now()
                newscatcher_requests({**self.params, 'multilingual_enabled': False},
                                     instant - timedelta(hours=self.params.get('lookback_hours', 24)), instant)
        return self


def set_profile_dashboards(db, profile, ids):
    ids = set(ids)
    found = set(db.scalars(select(PirSet.id).where(PirSet.id.in_(ids))))
    if ids != found:
        raise HTTPException(400, "Unknown dashboard")
    profile.dashboard_links = [ProfileDashboard(set_id=sid) for sid in ids]


@app.get("/api/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return [ser_profile(p) for p in db.scalars(select(SourceProfile).order_by(SourceProfile.id))]


@app.get('/api/profiles/{pid}/ingest-runs')
def ingest_runs(pid: int, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    db.get(SourceProfile, pid) or _404()
    runs = db.scalars(select(IngestRun).where(IngestRun.profile_id == pid)
                      .order_by(IngestRun.id.desc()).limit(limit)).all()
    outcomes = {}
    if runs:
        counts = db.execute(select(IngestRunArticle.run_id, Article.status, func.count())
                            .join(Article, Article.id == IngestRunArticle.article_id)
                            .where(IngestRunArticle.run_id.in_([r.id for r in runs]), IngestRunArticle.is_new.is_(True))
                            .group_by(IngestRunArticle.run_id, Article.status))
        for run_id, status, count in counts:
            outcomes.setdefault(run_id, {})[status] = count
    return [{**{k: getattr(r, k) for k in ('id', 'source', 'status', 'started_at', 'finished_at',
             'window_since', 'window_until', 'config_hash', 'returned_articles', 'new_articles',
             'duplicate_urls', 'duplicate_titles', 'excluded_articles', 'invalid_articles',
             'duration_ms', 'planned_requests', 'estimated_credits', 'error_code')},
             'tracked_requests': len(r.request_metrics), 'requests': r.request_metrics,
             'cap_warnings': sum(bool(m.get('cap_hit')) for m in r.request_metrics),
             'new_article_statuses': outcomes.get(r.id, {}),
             'new_articles_per_estimated_credit': r.new_articles / r.estimated_credits if r.estimated_credits else None,
             'cost_note': 'Nominal credit estimates, not provider billing; unknown charges remain null. '
                          'Classifier statuses are not analyst-validated relevance.'} for r in runs]


@app.post('/api/profiles/{pid}/catch-up-preview')
def catch_up_preview(pid: int, body: CatchUpPreviewIn, db: Session = Depends(get_db)):
    profile = db.get(SourceProfile, pid) or _404()
    run = db.get(IngestRun, body.evidence_run_id)
    if run is None or run.profile_id != pid:
        raise HTTPException(404, 'No such poll for this stream')
    try:
        ProfileIn(name=profile.name, source=profile.source, params=profile.params)
        return preview_catchup(db, profile, run, body, now())
    except ValueError as e:
        raise HTTPException(409, str(e))


def _profile_plan(params, db, *, illustrative=False):
    instant = now()
    return newscatcher_requests(params, instant - timedelta(hours=params.get('lookback_hours', 24)), instant,
                               plan={'max_articles_per_page': 100} if illustrative else None,
                               translation=keyword_translation.load_approved(db, params))


class TranslationPlanIn(BaseModel):
    params: dict = Field(default_factory=dict)


class TranslationApprovalIn(TranslationPlanIn):
    decisions: list[dict]
    confirmed: Literal[True]


def _validate_translation_draft(params):
    try:
        # Trusted server-side context, never a field clients can use to bypass saving guards.
        ProfileIn.model_validate({'name': 'Translation plan', 'params': params},
                                 context={'translation_draft': True})
    except ValidationError as error:
        raise ValueError('; '.join(item['msg'].removeprefix('Value error, ')
                                   for item in error.errors())) from None


@app.post('/api/ingestion/translation-plans')
def create_translation_plan(body: TranslationPlanIn, db: Session = Depends(get_db)):
    _validate_translation_draft(body.params)
    review = keyword_translation.create_review(db, body.params)
    db.commit()
    return keyword_translation.serialize_review(review, body.params)


@app.get('/api/ingestion/translation-plans/{review_id}')
def get_translation_plan(review_id: str, db: Session = Depends(get_db)):
    review = db.get(KeywordTranslationReview, review_id) or _404()
    return keyword_translation.serialize_review(review)


@app.post('/api/ingestion/translation-plans/{review_id}/generate')
def generate_translation_plan(review_id: str, db: Session = Depends(get_db)):
    review = keyword_translation.generate_missing(db, review_id)
    db.commit()
    return keyword_translation.serialize_review(review)


@app.post('/api/ingestion/translation-plans/{review_id}/approve')
def approve_translation_plan(review_id: str, body: TranslationApprovalIn, db: Session = Depends(get_db)):
    _validate_translation_draft(body.params)
    review = keyword_translation.approve_review(db, review_id, body.params, body.decisions)
    db.commit()
    return {'review': keyword_translation.serialize_review(review, body.params),
            'params_patch': {'multilingual_enabled': True, 'translation_review_id': review.id,
                             'translation_languages': review.payload['basis']['targets']},
            'note': 'Approved translations are frozen, but no stream was saved or activated. Preview and Save to apply.'}


@app.post("/api/profiles/preview-query")
def preview_query(body: ProfileIn, db: Session = Depends(get_db)):
    try:
        if body.source == 'gdelt':
            return {"query": gdelt_query(body.params)}
        batches = _profile_plan(body.params, db, illustrative=True)
        requests = [{'endpoint': V3_API if mode == 'v3' else f'{NEWS_API}/{mode}',
                     'method': 'GET' if mode == 'v3' else 'POST', 'parameters': payload,
                     'estimated_credits': request_credit_estimate(mode, payload),
                     'translation_language': batches.lanes[index], 'translation_review_id': batches.review_id}
                    for index, (mode, payload) in enumerate(batches)]
        first = requests[0]
        costs = [request['estimated_credits'] for request in requests]
        credits = sum(costs) if all(cost is not None for cost in costs) else None
        polls = math.ceil(30 * 24 * 60 / body.interval_minutes)
        request_limit, credit_limit = query_budget(body.params)
        return {'query': first['parameters']['q'], **first, 'requests': requests, 'request_count': len(requests),
                'vocabulary': vocabulary_summary(body.params),
                'query_planner_version': query_planner_version(body.params),
                'content_matching': {'mode': content_matching_settings(body.params, body.params.get('endpoint', 'search'))[0],
                                     'search_in': first['parameters'].get('search_in'),
                                     'note': 'Translated-content mode uses English queries against original and English-translated fields. No keyword-translation model calls or extra language lanes. Language restrictions remain unchanged; coverage is not guaranteed.'},
                'translations': {'enabled': bool(body.params.get('multilingual_enabled')), 'review_id': batches.review_id,
                                 'languages': keyword_translation.target_languages(body.params) if body.params.get('multilingual_enabled') else [],
                                 'emitted_language_lanes': sorted(set(batches.lanes) - {'original'}), 'original_query_retained': True},
                'budget': {'max_requests_per_poll': request_limit, 'max_credits_per_poll': credit_limit},
                'estimated_credits_per_poll': credits,
                'estimated_credits_per_30_days': credits * polls if credits is not None else None,
                'estimated_requests_per_30_days': len(requests) * polls,
                'estimated_polls_per_30_days': polls,
                'note': 'Credit figures use nominal pricing assumptions, not provider billing or a subscription quote. '
                        '30-day figures assume continuous scheduled polling; retries, manual runs and extra collection are excluded. '
                        'Vocabulary changes apply only after saving; existing streams default to frozen Legacy v1. '
                        'Expanded v1 is experimental and may remove broad legacy terms; evaluate relevance before promotion. '
                        'Automatic dates shown are a first-run example. Later runs use the last successful poll with overlap. '
                        'Explicit dates/search_window override scheduling windows and may replay the same period. '
                        'The provider subscription can cap page size/history; preview makes no API calls. '
                        'Oversized preset queries are split without dropping selections. Each request consumes API quota/credits; '
                        'the article limit applies per request and results are deduplicated. '
                        'Only one page is fetched per query part. Some fields require Enterprise access.'}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/profiles")
def create_profile(body: ProfileIn, db: Session = Depends(get_db)):
    if body.source == 'newscatcher':
        _profile_plan(body.params, db)
    p = SourceProfile(**body.model_dump(exclude={"dashboard_ids"}))
    set_profile_dashboards(db, p, body.dashboard_ids)
    db.add(p); db.commit()
    return ser_profile(p)


@app.put("/api/profiles/{pid}")
def update_profile(pid: int, body: ProfileIn, db: Session = Depends(get_db)):
    if body.source == 'newscatcher':
        _profile_plan(body.params, db)
    p = db.get(SourceProfile, pid) or _404()
    set_profile_dashboards(db, p, body.dashboard_ids)
    for k, v in body.model_dump(exclude={"dashboard_ids"}).items():
        setattr(p, k, v)
    db.commit()
    return ser_profile(p)


@app.delete("/api/profiles/{pid}")
def delete_profile(pid: int, db: Session = Depends(get_db)):
    db.delete(db.get(SourceProfile, pid) or _404()); db.commit()
    return {"ok": True}


@app.post("/api/profiles/{pid}/run")
def run_now(pid: int, db: Session = Depends(get_db)):
    """Mark the profile due; the worker picks it up on its next tick."""
    p = db.get(SourceProfile, pid) or _404()
    if not p.enabled:
        raise HTTPException(409, "Stream is paused; enable and save it before running")
    request_poll(p, now())
    p.last_status = (p.last_status or "") + " · queued"
    db.commit()
    return ser_profile(p)


# ---------------- guided dashboard setup ----------------
def _setup_profiles(body: DashboardSetupIn, db: Session):
    ids = set(body.profile_ids)
    profiles = list(db.scalars(select(SourceProfile).where(SourceProfile.id.in_(ids))))
    if len(profiles) != len(ids):
        raise HTTPException(400, "One or more selected streams no longer exist")
    return profiles


@app.post("/api/dashboard-setup/preview")
def preview_dashboard_setup(body: DashboardSetupIn, db: Session = Depends(get_db)):
    profiles = _setup_profiles(body, db)
    dashboard = compile_dashboard(body)
    return {"name": dashboard.name, "description": dashboard.description,
            "requirements": [{"code": p.code, "title": p.title, "question": p.question,
                              "indicators": p.indicators, "priority": p.priority} for p in dashboard.pirs],
            "system_prompt": build_system_prompt([dashboard]),
            "streams": [{"id": p.id, "name": p.name, "enabled": p.enabled} for p in profiles]}


@app.post("/api/dashboard-setup")
def create_dashboard_setup(body: DashboardSetupIn, db: Session = Depends(get_db)):
    profiles = _setup_profiles(body, db)
    dashboard = compile_dashboard(body)
    # Flush the set first so requirement codes have a unique dashboard prefix.
    requirements = list(dashboard.pirs)
    dashboard.pirs = []
    db.add(dashboard)
    db.flush()
    for i, requirement in enumerate(requirements, 1):
        requirement.code = f"D{dashboard.id}-{i}"
        dashboard.pirs.append(requirement)
    for profile in profiles:
        db.add(ProfileDashboard(profile_id=profile.id, set_id=dashboard.id))
    queued = 0
    if body.reclassify_days:
        result = db.execute(update(Article).where(
            profile_scope([p.id for p in profiles]),
            Article.published_at >= now() - timedelta(days=body.reclassify_days),
            Article.status.in_(["enriched", "irrelevant", "failed"]),
        ).values(status="pending", error=None))
        queued = result.rowcount
    db.commit()
    return {"set": ser_set(dashboard), "queued": queued,
            "claude_configured": bool(get_settings().anthropic_api_key),
            "classify_configured": model_settings.purpose_configured(db, 'classify', get_settings())}


@app.get("/api/dashboards/{sid}/processing")
def dashboard_processing(sid: int, db: Session = Depends(get_db)):
    _load_set(db, sid)
    counts = dict(db.execute(select(Article.status, func.count()).where(dashboard_scope(sid))
                             .group_by(Article.status)).all())
    matched = db.scalar(select(func.count()).select_from(_article_query(set_id=sid)
                        .where(Article.status == "enriched").subquery()))
    return {"counts": counts, "matched": matched,
            "claude_configured": bool(get_settings().anthropic_api_key),
            "classify_configured": model_settings.purpose_configured(db, 'classify', get_settings())}


# ---------------- PIR sets & PIRs ----------------
class SetIn(BaseModel):
    name: str
    description: str = ""


class PirIn(BaseModel):
    code: str
    title: str
    question: str
    indicators: str = ""
    priority: int = Field(2, ge=1, le=3)
    active: bool = True


def _load_set(db: Session, sid: int) -> PirSet:
    ps = db.scalars(select(PirSet).options(selectinload(PirSet.pirs)).where(PirSet.id == sid)).first()
    return ps or _404()


@app.get("/api/pir-sets")
def list_sets(db: Session = Depends(get_db)):
    return [ser_set(ps) for ps in db.scalars(select(PirSet).options(selectinload(PirSet.pirs)).order_by(PirSet.id))]


@app.post("/api/pir-sets")
def create_set(body: SetIn, db: Session = Depends(get_db)):
    ps = PirSet(**body.model_dump()); db.add(ps); db.commit()
    return ser_set(_load_set(db, ps.id))


@app.put("/api/pir-sets/{sid}")
def update_set(sid: int, body: SetIn, db: Session = Depends(get_db)):
    ps = _load_set(db, sid)
    ps.name, ps.description = body.name, body.description
    db.commit()
    return ser_set(ps)


@app.delete("/api/pir-sets/{sid}")
def delete_set(sid: int, db: Session = Depends(get_db)):
    db.delete(_load_set(db, sid)); db.commit()
    return {"ok": True}


@app.post("/api/pir-sets/{sid}/pirs")
def create_pir(sid: int, body: PirIn, db: Session = Depends(get_db)):
    _load_set(db, sid)
    if db.scalar(select(Pir.id).where(Pir.code == body.code)):
        raise HTTPException(409, f"PIR code {body.code} already exists")
    p = Pir(set_id=sid, **body.model_dump()); db.add(p); db.commit()
    return ser_pir(p)


@app.put("/api/pirs/{pid}")
def update_pir(pid: int, body: PirIn, db: Session = Depends(get_db)):
    p = db.get(Pir, pid) or _404()
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return ser_pir(p)


@app.delete("/api/pirs/{pid}")
def delete_pir(pid: int, db: Session = Depends(get_db)):
    db.delete(db.get(Pir, pid) or _404()); db.commit()
    return {"ok": True}


# ---------------- articles (the stream) ----------------
def _article_query(*, q=None, profile_id=None, event_type=None, region=None, country=None, pir_id=None,
                   set_id=None, since=None, until=None, include_irrelevant=False, status=None, has_geo=False):
    stmt = select(Article)
    if status:
        stmt = stmt.where(Article.status == status)
    elif include_irrelevant:
        stmt = stmt.where(Article.status.in_(["enriched", "irrelevant", "pending", "failed"]))
    else:
        stmt = stmt.where(Article.status.in_(["enriched", "pending"]))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Article.title.ilike(like), Article.ai_summary.ilike(like),
                              Article.location_name.ilike(like)))
    if profile_id:
        stmt = stmt.where(profile_scope([profile_id]))
    if event_type:
        stmt = stmt.where(Article.event_type == event_type)
    if region:
        stmt = stmt.where(Article.region == region)
    if country:
        # JSON list column; a LIKE on its text form works on both Postgres and SQLite
        stmt = stmt.where(cast(Article.countries, Text).ilike(f'%"{country.upper()}"%'))
    if pir_id:
        stmt = stmt.where(Article.matches.any(ArticlePir.pir_id == pir_id))
    if set_id:
        stmt = stmt.where(Article.matches.any(ArticlePir.pir.has(Pir.set_id == set_id)), dashboard_scope(set_id))
    if since:
        stmt = stmt.where(Article.published_at >= since)
    if until:
        stmt = stmt.where(Article.published_at < until)
    if has_geo:
        stmt = stmt.where(and_(Article.lat.is_not(None), Article.lon.is_not(None)))
    return stmt


@app.get("/api/articles")
def list_articles(
    db: Session = Depends(get_db),
    q: str | None = None, profile_id: int | None = None, event_type: str | None = None,
    region: str | None = None, country: str | None = None, pir_id: int | None = None,
    set_id: int | None = None, window: str | None = None, include_irrelevant: bool = False,
    status: str | None = None, limit: int = Query(50, le=500), offset: int = 0,
):
    since = now() - parse_window(window) if window else None
    stmt = _article_query(q=q, profile_id=profile_id, event_type=event_type, region=region, country=country,
                          pir_id=pir_id, set_id=set_id, since=since, include_irrelevant=include_irrelevant,
                          status=status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.options(selectinload(Article.matches).selectinload(ArticlePir.pir))
                       .order_by(Article.published_at.desc()).limit(limit).offset(offset)).all()

    facet_base = stmt.subquery()
    facets = {
        "event_type": dict(db.execute(select(facet_base.c.event_type, func.count())
                                      .group_by(facet_base.c.event_type)).all()),
        "region": dict(db.execute(select(facet_base.c.region, func.count()).group_by(facet_base.c.region)).all()),
    }
    facets = {k: {str(kk): vv for kk, vv in v.items() if kk} for k, v in facets.items()}
    return {"total": total, "items": [ser_article(a) for a in items], "facets": facets}


# ---------------- dashboards ----------------
@app.get('/api/overview')
def overview(window: Literal['24h', '7d', '30d', '90d'] = '7d', db: Session = Depends(get_db)):
    at = now()
    since = at - parse_window(window)
    sets = list(db.scalars(select(PirSet).options(selectinload(PirSet.pirs)).order_by(PirSet.id)))
    # The globe shows every geolocated article in the period, aggregated per place
    # (~1 km grid) with the latest reports kept as click-through samples. A scan cap
    # bounds response size for very large installations.
    scan_limit, sample_limit = 20000, 20
    limit = scan_limit
    dashboards = []
    for ps in sets:
        activity = set_activity(db, ps.id, window, at)
        conditions = set_article_conditions(ps.id, since, at)
        geo = (Article.lat.between(-90, 90), Article.lon.between(-180, 180))
        located = db.scalar(select(func.count()).select_from(Article).where(*conditions, *geo))
        rows = db.execute(select(Article.id, Article.title, Article.url, Article.lat, Article.lon,
                                 Article.published_at, Article.location_name, Article.geo_precision)
                          .where(*conditions, *geo).order_by(Article.published_at.desc(), Article.id.desc()).limit(scan_limit))
        places = {}
        for row in rows:
            report = {**dict(row._mapping), 'published_at': row.published_at.isoformat()}
            key = (round(row.lat, 2), round(row.lon, 2))
            place = places.setdefault(key, {'id': row.id, 'lat': row.lat, 'lon': row.lon, 'count': 0, 'reports': []})
            place['count'] += 1
            if len(place['reports']) < sample_limit:
                place['reports'].append(report)
        points = list(places.values())
        shown = sum(p['count'] for p in points)
        dashboards.append({'id': ps.id, 'name': ps.name, 'pir_count': sum(p.active for p in ps.pirs),
                           **activity, 'geolocated_count': located, 'unlocated_count': activity['count'] - located,
                           'points': points, 'points_truncated': located > shown})
    return {'window': window, 'generated_at': at.isoformat(), 'point_limit_per_dashboard': limit,
            'dashboards': dashboards}


@app.get("/api/dashboards/{sid}")
def dashboard(sid: int, window: str = "7d", db: Session = Depends(get_db)):
    ps = _load_set(db, sid)
    pirs = [p for p in ps.pirs if p.active]
    since = now() - parse_window(window)
    stats = pir_stats(db, pirs, window)

    rows = db.scalars(
        _article_query(set_id=sid, since=since).where(Article.status == "enriched")
        .options(selectinload(Article.matches).selectinload(ArticlePir.pir))
        .order_by(Article.published_at.desc()).limit(1000)
    ).all()
    set_pir_ids = {p.id for p in pirs}
    articles = []
    for a in rows:
        d = ser_article(a)
        d["pirs"] = [m for m in d["pirs"] if m["pir_id"] in set_pir_ids]
        articles.append(d)
    streams = db.scalars(select(SourceProfile).join(ProfileDashboard).where(ProfileDashboard.set_id == sid)).all()
    return {"set": ser_set(ps), "window": window, "stats": stats, "articles": articles,
            "streams": [{"id": p.id, "name": p.name} for p in streams], "total": len(articles)}


# ---------------- summaries ----------------
class SummaryIn(BaseModel):
    period: str = "7d"


@app.get("/api/pir-sets/{sid}/summaries")
def list_summaries(sid: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(Summary).where(Summary.set_id == sid).order_by(Summary.created_at.desc()).limit(50))
    return [ser_summary(x) for x in rows]


@app.post("/api/pir-sets/{sid}/summaries")
def create_summary(sid: int, body: SummaryIn, db: Session = Depends(get_db)):
    _load_set(db, sid)
    if not model_settings.purpose_configured(db, 'summary', get_settings()):
        raise HTTPException(400, 'The selected summary provider is not configured')
    try:
        label, start, end = period_bounds(body.period, now())
    except ValueError as e:
        raise HTTPException(400, str(e))
    x = Summary(set_id=sid, period_label=label, period_start=start, period_end=end)
    db.add(x); db.commit()
    return ser_summary(x)


@app.get("/api/summaries/{xid}")
def get_summary(xid: int, db: Session = Depends(get_db)):
    return ser_summary(db.get(Summary, xid) or _404(), full=True)


@app.get('/api/summaries/{xid}/export')
def export_summary(xid: int, format: Literal['html', 'md', 'txt', 'json'] = 'html', db: Session = Depends(get_db)):
    summary = db.get(Summary, xid) or _404()
    if summary.status != 'done' or not summary.content:
        raise HTTPException(409, 'Only completed summaries can be exported')
    dashboard = db.get(PirSet, summary.set_id) or _404()
    content, media, filename = report_export(summary, dashboard.name, format, logo_data_uri=branding.data_uri(db))
    return Response(content, media_type=media, headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    })


def _editable_summary(db: Session, xid: int) -> Summary:
    row = db.scalar(select(Summary).where(Summary.id == xid).with_for_update(skip_locked=True))
    if row is None:
        if db.get(Summary, xid) is None:
            _404()
        raise HTTPException(409, "This summary is being generated. Try again after it finishes.")
    return row


@app.post('/api/summaries/{xid}/retry')
def retry_summary(xid: int, db: Session = Depends(get_db)):
    row = _editable_summary(db, xid)
    if row.status != 'failed':
        raise HTTPException(409, 'Only failed summaries can be retried')
    if not model_settings.purpose_configured(db, 'summary', get_settings()):
        raise HTTPException(400, 'The selected summary provider is not configured')
    row.status, row.error = 'pending', None
    db.commit()
    return ser_summary(row)


@app.delete("/api/summaries/{xid}")
def delete_summary(xid: int, db: Session = Depends(get_db)):
    db.delete(_editable_summary(db, xid)); db.commit()
    return {"ok": True}


def _404():
    raise HTTPException(404, "not found")


# ---------------- frontend ----------------
@app.get('/static/{name}.js')
def frontend_module(name: str):
    # Version transitive imports too: all maps share a renderer, which must never
    # come from a different deployment than the importing dashboard module.
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
        _404()
    path = FRONTEND / f'{name}.js'
    if not path.is_file():
        _404()
    script = path.read_text()
    script = re.sub(r"(['\"])(\./[^'\"]+\.js)\1",
                    lambda m: f'{m[1]}{m[2]}?v={UI_VERSION}{m[1]}', script)
    return Response(script, media_type='text/javascript')


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    html = (FRONTEND / 'index.html').read_text()
    development = get_settings().app_environment == 'development'
    badge = '<span id="environment-badge" class="environment-badge">DEVELOPMENT</span>' if development else ''
    html = html.replace('<!-- environment-badge -->', badge)
    if development:
        html = html.replace('<title>Intel Ingest</title>', '<title>[DEV] Intel Ingest</title>')
    for asset in ('app.js', 'styles.css'):
        html = html.replace(f'/static/{asset}', f'/static/{asset}?v={UI_VERSION}')
    return HTMLResponse(html)


@app.exception_handler(ValueError)
def _value_error(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

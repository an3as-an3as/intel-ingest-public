"""Read-only Articles catch-up preview. No transport, scheduling or database writes."""
import hashlib
import json
import math
from datetime import timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from ..sources.keyword_translation import load_approved
from ..sources.newscatcher import NEWS_API, build_requests, query_budget, request_credit_estimate
from ..sources.newscatcher_filters import mode_for


class ArticlesEntitlement(BaseModel):
    """Explicit offline operator evidence, never represented as live-verified access."""
    model_config = ConfigDict(extra='forbid')
    confirmed: StrictBool
    reference: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    history_start: AwareDatetime
    max_articles_per_page: int = Field(ge=1, le=100, strict=True)

    @model_validator(mode='after')
    def confirmation(self):
        if not self.confirmed or not self.reference.strip():
            raise ValueError('Confirm current Articles entitlement and supply a non-secret evidence reference')
        return self


class CatchUpPreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_run_id: int = Field(ge=1, strict=True)
    window_start: AwareDatetime
    window_end: AwareDatetime
    window_minutes: int = Field(ge=1, le=1440, strict=True)
    max_requests: int = Field(ge=1, le=16, strict=True)
    max_credits: int = Field(ge=1, le=10000, strict=True)
    entitlement: ArticlesEntitlement | None = None


def config_hash(params):
    # Same revision representation as the existing ingestion ledger. Do not mutate it.
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def evidence_reasons(run):
    reasons = []
    if any(m.get('cap_hit') for m in run.request_metrics or []):
        reasons.append('result_cap')
    if any(m.get('history_clamped') for m in run.request_metrics or []):
        reasons.append('history_clamped')
    if run.status in {'partial', 'error'}:
        reasons.append('incomplete_poll')
    return reasons


def preview_catchup(db, profile, run, body: CatchUpPreviewIn, at):
    params = profile.params or {}
    if profile.source != 'newscatcher' or mode_for(params) != 'articles':
        raise ValueError('UNSUPPORTED_ENDPOINT: catch-up preview requires a saved Articles stream. '
                         'Search has no arbitrary historical paging; Search/v3/GDELT are not converted.')
    if run.profile_id != profile.id or run.source != 'newscatcher':
        raise ValueError('WRONG_EVIDENCE: select a NewsCatcher poll belonging to this stream')
    if run.finished_at is None or run.status not in {'success', 'partial', 'error'}:
        raise ValueError('UNFINISHED_EVIDENCE: select a finished poll')
    if run.config_hash != config_hash(params):
        raise ValueError('STALE_EVIDENCE: saved search settings differ from this poll; no historical query is guessed')
    reasons = evidence_reasons(run)
    if not reasons:
        raise ValueError('NO_COMPLETENESS_EVIDENCE: select a capped, history-clamped, partial or failed poll. '
                         'Indexing delay cannot be inferred from a successful poll alone.')
    native = params.get('native_filters', {})
    if set(native) & {'from_date', 'to_date', 'page', 'search_window', 'from_', 'to_'}:
        raise ValueError('EXPLICIT_WINDOW_FILTER: saved date/page controls cannot be overwritten or silently removed. '
                         'This preview supports only streams without explicit date/page overrides.')
    start, end = body.window_start, body.window_end
    if not start < end <= at:
        raise ValueError('INVALID_WINDOW: use a non-empty interval ending no later than now')
    if start < run.window_since or end > run.window_until:
        raise ValueError('OUTSIDE_EVIDENCE_WINDOW: choose an interval within the selected poll\'s requested window')
    entitlement = body.entitlement
    if entitlement is None:
        raise ValueError('ENTITLEMENT_UNKNOWN: supply explicit recent Articles access, archive boundary and page-size evidence. '
                         'No subscription lookup is performed.')
    if not at - timedelta(hours=24) <= entitlement.observed_at <= at:
        raise ValueError('ENTITLEMENT_STALE: evidence must be from the past 24 hours, not the future')
    if start < entitlement.history_start:
        raise ValueError('HISTORY_UNAVAILABLE: requested dates precede the declared archive boundary; no dates are truncated')
    stream_requests, stream_credits = query_budget(params)
    request_limit = min(body.max_requests, stream_requests)
    credit_limit = min(body.max_credits, stream_credits) if stream_credits is not None else body.max_credits
    span = timedelta(minutes=body.window_minutes)
    window_count = math.ceil((end - start) / span)
    # Every window needs at least one Articles request (nominally five credits).
    if window_count > request_limit or window_count * 5 > credit_limit:
        raise ValueError('CATCHUP_BUDGET_EXCEEDED: the full interval needs at least '
                         f'{window_count} requests / {window_count * 5} nominal credits. '
                         'Use a smaller interval or an explicitly larger allowed budget; no windows are dropped.')
    translation = load_approved(db, params)
    requests, windows = [], []
    credits = 0
    for index in range(window_count):
        lower = start + index * span
        upper = min(lower + span, end)
        plan = build_requests(params, lower, upper, api_version='news', translation=translation,
                              plan={'articles': {'max_articles_per_page': entitlement.max_articles_per_page}})
        window = {'index': index + 1, 'from_date': lower.isoformat(), 'to_date': upper.isoformat(),
                  'request_count': len(plan)}
        windows.append(window)
        for part, (mode, payload) in enumerate(plan):
            if mode != 'articles' or payload.get('page') != 1:
                raise ValueError('UNSUPPORTED_PAGING: only Articles page 1 per explicit window is planned')
            cost = request_credit_estimate(mode, payload)
            if cost is None:
                raise ValueError('CREDIT_ESTIMATE_UNAVAILABLE: refusing an unknown-cost plan')
            credits += cost
            requests.append({'window': index + 1, 'method': 'POST', 'endpoint': NEWS_API + '/articles',
                             'parameters': payload, 'estimated_credits': cost,
                             'translation_language': plan.lanes[part], 'translation_review_id': plan.review_id})
        if len(requests) > request_limit or credits > credit_limit:
            raise ValueError('CATCHUP_BUDGET_EXCEEDED: all windows, query parts and language lanes share one total '
                             'budget; the complete plan was rejected, not truncated')
    return {
        'preview_only': True, 'executable': False, 'profile_id': profile.id, 'config_hash': run.config_hash,
        'evidence': {'run_id': run.id, 'reasons': reasons, 'status': run.status,
                     'window_since': run.window_since.isoformat(), 'window_until': run.window_until.isoformat()},
        'entitlement': {**entitlement.model_dump(mode='json'), 'status': 'operator-declared; not live-verified'},
        'window_count': window_count, 'windows': windows, 'request_count': len(requests), 'requests': requests,
        'estimated_credits': credits,
        'budget': {'max_requests': request_limit, 'max_credits': credit_limit,
                   'scope': 'entire preview, including all windows/query parts/language lanes'},
        'coverage': 'uncertain', 'indexing_delay': 'not measured',
        'warnings': [
            'Preview only: zero requests sent; no articles, schedules, run records or successful watermarks changed.',
            'Nominal Articles estimate: 5 credits per request, not actual billing or a monthly spending cap. '
            'Translation and downstream classification costs are excluded.',
            'Entitlement is an operator declaration, not a provider-verified subscription or access guarantee.',
            'One page per query/language part per window. Smaller windows can still saturate; completeness is not guaranteed.',
            'Effective page size is the smaller of the saved article cap, declared entitlement and endpoint maximum (100).',
            'Adjacent date windows share a boundary; provider inclusivity can produce overlaps. No deduplication is executed.',
            'No pagination, adaptive retries, indexing-delay measurement or automatic catch-up execution is implemented.',
        ],
    }

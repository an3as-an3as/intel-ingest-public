#!/usr/bin/env python3
"""Offline Stage-4 Chromium/API smoke. Same Playwright prerequisites as test_stages_browser.py.

Run: python scripts/test_catchup_browser.py
Validates the pinned development boundaries, then serves actual UI/API through
TestClient with a disposable SQLite fixture. No service is started/deployed and
all external browser/provider transports are blocked.
"""
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://intel-catchup-fixture.test'


def main():
    subprocess.run([str(ROOT / 'scripts/development.sh'), 'check'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='intel-catchup-browser-') as directory:
        os.environ.update(DATABASE_URL=f'sqlite:///{directory}/fixture.db', APP_ENVIRONMENT='development', APP_PASSWORD='',
                          ANTHROPIC_API_KEY='', NEWSCATCHER_API_KEY='', KEYWORD_TRANSLATION_ALLOW_LIVE='false',
                          FETCH_ARTICLE_TEXT='false', GDELT_FALLBACK_TO_NEWSCATCHER='false')
        sys.path.insert(0, str(ROOT / 'backend'))
        from fastapi.testclient import TestClient
        from playwright.sync_api import expect, sync_playwright
        from sqlalchemy import select
        from app.db import Base, engine, session_scope
        from app.main import app
        from app.models import IngestRun, IngestState, SourceProfile
        from app.pipeline.catchup import config_hash

        attempts = []
        def blocked(*args, **kwargs):
            attempts.append('provider transport attempted')
            raise AssertionError('Provider calls are forbidden')

        with patch('requests.sessions.Session.request', side_effect=blocked), \
             patch('httpx.HTTPTransport.handle_request', side_effect=blocked), \
             TestClient(app, base_url=BASE) as client, sync_playwright() as playwright:
            at = datetime.now(timezone.utc).replace(microsecond=0)
            with session_scope() as db:
                params = {'endpoint': 'articles', 'keywords': ['Baltic Sea'], 'languages': ['en'],
                          'source_countries': ['DK'], 'exclude_keywords': ['sport'], 'max_requests_per_poll': 4,
                          'max_credits_per_poll': 20, 'native_filters': {'exclude_duplicates': False, 'word_count_min': 0}}
                profile = SourceProfile(name='Disposable catch-up fixture', source='newscatcher', params=params,
                                        enabled=False, interval_minutes=60, last_run_at=at-timedelta(days=1))
                db.add(profile); db.flush(); pid = profile.id
                profile.ingest_state = IngestState(last_success_at=at-timedelta(days=1), last_attempt_at=at,
                                                   failures=1, run_requested=True, retry_at=at+timedelta(minutes=5))
                db.add(IngestRun(profile_id=pid, source='newscatcher', started_at=at-timedelta(seconds=1), finished_at=at,
                                 status='partial', window_since=at-timedelta(hours=2), window_until=at,
                                 config_hash=config_hash(params), planned_requests=2,
                                 request_metrics=[{'part': 1, 'endpoint': 'articles', 'status': 'success',
                                                   'returned': 20, 'limit': 20, 'cap_hit': True}]))
            def snapshot():
                with session_scope() as db:
                    return {t.name: copy.deepcopy([dict(r) for r in db.execute(select(t)).mappings()])
                            for t in Base.metadata.sorted_tables}
            before = snapshot()
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors, posts = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def serve(route):
                    request = route.request
                    url = urlsplit(request.url)
                    if url.netloc != 'intel-catchup-fixture.test':
                        if 'anthropic' in url.netloc or 'newscatcher' in url.netloc:
                            attempts.append(request.url)
                        route.abort(); return
                    if request.method != 'GET':
                        posts.append((request.method, url.path))
                    headers = {k: v for k, v in request.headers.items() if k not in {'host', 'content-length'}}
                    response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                              content=request.post_data_buffer, headers=headers)
                    headers = {k: v for k, v in response.headers.items()
                               if k not in {'content-length', 'content-encoding', 'transfer-encoding'}}
                    route.fulfill(status=response.status_code, headers=headers, body=response.content)
                page.route('**/*', serve)
                page.goto(BASE + '/#/ingestion', wait_until='networkidle')
                expect(page.locator('#environment-badge')).to_have_text('DEVELOPMENT')
                saved = page.locator(f'[data-prof="{pid}"]')
                saved.locator('[data-collection-profile] > summary').click()
                saved.locator('[data-collection-refresh]').click()
                saved.locator('[data-catchup] > summary').click()
                form = saved.locator('[data-catchup-form]')
                output = form.locator('[data-catchup-result]')
                assert not posts, 'Opening diagnostics must not make a POST'
                form.locator('[name=catchup_reference]').fill('Synthetic offline entitlement note')
                def fill_date(name, value):
                    local = page.evaluate('(s) => {const d=new Date(s); return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,23)}', value.isoformat())
                    form.locator(f'[name={name}]').fill(local)
                fill_date('catchup_observed', at)
                fill_date('catchup_history', at-timedelta(days=30))
                form.locator('[name=catchup_page_size]').fill('20')
                form.locator('[name=catchup_confirmed]').check()
                form.locator('[data-catchup-preview]').click()
                expect(output).to_contain_text('CATCHUP_BUDGET_EXCEEDED')
                assert snapshot() == before, 'Rejected preview changed data'
                form.locator('[name=catchup_requests]').fill('2')
                form.locator('[name=catchup_credits]').fill('10')
                form.locator('[data-catchup-preview]').click()
                expect(output).to_contain_text('2 requests / 10 nominal credits TOTAL')
                expect(output).to_contain_text('operator-declared; not live-verified')
                expect(output).to_contain_text('Coverage remains uncertain')
                expect(output).to_contain_text('Baltic Sea')
                expect(output).to_contain_text('NOT sport')
                assert snapshot() == before, 'Successful preview changed data'
                assert form.locator('button').count() == 1, 'No execute/save action should exist'
                form.locator('[name=catchup_credits]').fill('15')
                expect(output).to_contain_text('Inputs changed')
                page.set_viewport_size({'width': 390, 'height': 844})
                form.locator('[data-catchup-preview]').scroll_into_view_if_needed()
                form.locator('[data-catchup-preview]').click()
                expect(output).to_contain_text('2 requests / 10 nominal credits TOTAL')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), 'Mobile page overflow'
                assert snapshot() == before
                assert posts == [('POST', f'/api/profiles/{pid}/catch-up-preview')] * 3, posts
                assert not attempts and not errors, (attempts, errors)
                print('PASS Stage 4 browser: actual API/UI, budget refusal, complete preview, stale-input invalidation, desktop/mobile, zero provider calls and unchanged database.')
            finally:
                browser.close()
        engine.dispose()


if __name__ == '__main__':
    main()

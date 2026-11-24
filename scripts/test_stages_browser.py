#!/usr/bin/env python3
"""Offline stages 2–3 acceptance smoke: real Chromium UI + FastAPI, disposable DB.

Run from this worktree with a test virtualenv containing backend/requirements-dev.txt:
  python -m pip install playwright
  python -m playwright install chromium
  python scripts/test_stages_browser.py

Runs the pinned isolation validator first. Browser HTTP is served by TestClient;
external browser requests are blocked. Provider transports fail closed. No running
stack, worker, credentials or persistent database is used or changed. The script
requires no /tmp scripts, intercepted fake API responses or sample production data.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://intel-fixture.test'


def main():
    subprocess.run([str(ROOT / 'scripts/development.sh'), 'check'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='intel-stages-browser-') as directory:
        os.environ.update(
            DATABASE_URL=f'sqlite:///{directory}/fixture.db', APP_ENVIRONMENT='development',
            APP_PASSWORD='', ANTHROPIC_API_KEY='', NEWSCATCHER_API_KEY='',
            KEYWORD_TRANSLATION_ALLOW_LIVE='false', FETCH_ARTICLE_TEXT='false',
            GDELT_FALLBACK_TO_NEWSCATCHER='false',
        )
        sys.path.insert(0, str(ROOT / 'backend'))
        from fastapi.testclient import TestClient
        from playwright.sync_api import sync_playwright, expect
        from sqlalchemy import func, select
        from app.db import engine, session_scope
        from app.main import app
        from app.models import Article, KeywordTranslationReview, SourceProfile

        provider_attempts = []
        def blocked(*args, **kwargs):
            provider_attempts.append('transport attempted')
            raise AssertionError('External provider transport is forbidden in this smoke test')

        with patch('requests.sessions.Session.request', side_effect=blocked), \
             patch('httpx.HTTPTransport.handle_request', side_effect=blocked), \
             TestClient(app, base_url=BASE) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors, api_requests, external_provider_requests = [], [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                accept = False
                dialogs = []
                def dialog_handler(dialog):
                    dialogs.append(dialog.message)
                    dialog.accept() if accept else dialog.dismiss()
                page.on('dialog', dialog_handler)

                def serve(route):
                    request = route.request
                    url = urlsplit(request.url)
                    if url.netloc != 'intel-fixture.test':
                        if 'anthropic' in url.netloc or 'newscatcher' in url.netloc:
                            external_provider_requests.append(request.url)
                        route.abort()
                        return
                    path = url.path + (f'?{url.query}' if url.query else '')
                    if path.startswith('/api/'):
                        api_requests.append((request.method, url.path))
                    headers = {k: v for k, v in request.headers.items()
                               if k.lower() not in {'host', 'content-length'}}
                    response = client.request(request.method, path, content=request.post_data_buffer, headers=headers)
                    headers = {k: v for k, v in response.headers.items()
                               if k.lower() not in {'content-length', 'content-encoding', 'transfer-encoding'}}
                    route.fulfill(status=response.status_code, headers=headers, body=response.content)
                page.route('**/*', serve)

                def profiles():
                    return client.get('/api/profiles').json()

                def open_sections(scope):
                    scope.locator('[data-profile-section]').evaluate_all('(nodes) => nodes.forEach(n => n.open = true)')
                    scope.locator('[data-event-vocabulary]').evaluate_all('(nodes) => nodes.forEach(n => { for(let p=n.parentElement; p; p=p.parentElement) if(p.tagName === "DETAILS") p.open=true; })')

                def tick(scope, name, label, checked=True):
                    open_sections(scope)
                    picker = scope.locator(f'select[name="{name}"] + section.multi-picker')
                    picker.locator('input[type=search]').fill(label)
                    picker.get_by_role('checkbox', name=label, exact=True).set_checked(checked)

                def open_ingestion():
                    page.goto(BASE + '/#/ingestion', wait_until='networkidle')
                    expect(page.locator('#environment-badge')).to_have_text('DEVELOPMENT')
                    assert page.title().startswith('[DEV]')
                    form = page.locator('#new-prof')
                    form.locator('[data-stream-mode]').click()
                    open_sections(form)
                    return form

                def preview(form, *, rejected=False):
                    with page.expect_response(lambda r: '/api/profiles/preview-query' in r.url) as pending:
                        form.locator('[data-preview]').click()
                    response = pending.value
                    assert (response.status >= 400 if rejected else response.status == 200), response.text()
                    return response.json()

                def approve(box):
                    box.locator('[data-translation-confirm]').check()
                    with page.expect_response(lambda r: r.url.endswith('/approve')) as pending:
                        box.locator('[data-translation-approve]').click()
                    assert pending.value.status == 200, pending.value.text()
                    expect(box.locator('[data-translation-message]')).to_contain_text('Approved, not saved')

                # Stage 2: defaults, complete split plans, rejection, confirmation and persistence.
                form = open_ingestion()
                expect(form.locator('[name=event_vocabulary_version]')).to_have_value('legacy-v1')
                expect(form.locator('[name=multilingual_enabled]')).not_to_be_checked()
                form.locator('[name=name]').fill('Disposable vocabulary fixture')
                form.locator('[name=keywords]').fill('Baltic Sea')
                form.locator('[name=exclude_keywords]').fill('sport')
                form.locator('[name=interval_minutes]').select_option('60')
                tick(form, 'event_presets', 'Cyber')
                for country in ['Estonia', 'Latvia', 'Lithuania']:
                    tick(form, 'coverage_countries', country)
                tick(form, 'nc_languages', 'English')
                form.locator('[name=event_vocabulary_version]').select_option('expanded-v1')
                tick(form, 'event_vocabulary_tiers', 'Indicators — related signals (optional)')
                tick(form, 'event_vocabulary_tiers', 'Discovery — broad terms, more noise (optional)')
                form.locator('[name=max_requests_per_poll]').fill('1')
                assert 'more than 1' in str(preview(form, rejected=True))
                form.locator('[name=max_requests_per_poll]').fill('3')
                form.locator('[name=max_credits_per_poll]').fill('1')
                assert 'credit' in str(preview(form, rejected=True)).lower()
                form.locator('[name=max_credits_per_poll]').fill('3')
                plan = preview(form)
                assert plan['request_count'] == 2, plan
                assert plan['estimated_credits_per_poll'] == 2
                for request in plan['requests']:
                    payload = request['parameters']
                    assert len(payload['q']) <= 500
                    assert 'Baltic Sea' in payload['q'] and 'NOT sport' in payload['q']
                    assert payload['languages'] == ['en'], payload
                    for country in ['Estonia', 'Latvia', 'Lithuania']:
                        assert country in payload['q']
                for term in plan['vocabulary']['terms']:
                    assert any(term in r['parameters']['q'] for r in plan['requests']), term
                expect(form.locator('[data-q]')).to_contain_text('Added vs Legacy v1')
                expect(form.locator('[data-q]')).to_contain_text('Removed vs Legacy v1')
                assert not profiles()
                form.locator('[data-stream-review-confirm]').check()
                with page.expect_event('dialog'):
                    form.locator('[data-stream-actions] button.primary').click()
                assert len(dialogs) == 1 and not profiles(), 'Cancelled confirmation saved a stream'
                accept = True
                form.locator('[data-stream-actions] button.primary').click()
                page.wait_for_url('**/#/settings/profiles/*')
                stored = profiles()[0]
                vocabulary_id = stored['id']
                assert not stored['enabled']
                form = open_ingestion()
                page.reload(wait_until='networkidle')
                saved = page.locator(f'[data-prof="{vocabulary_id}"]')
                open_sections(saved)
                expect(saved.locator('[name=event_vocabulary_version]')).to_have_value('expanded-v1')
                tiers = saved.locator('[name=event_vocabulary_tiers]').evaluate('(s) => [...s.selectedOptions].map(o => o.value)')
                assert tiers == ['core', 'indicators', 'discovery']
                # Cancelling an edit must preserve an existing stored stream too.
                saved.locator('[name=max_requests_per_poll]').fill('4')
                accept = False
                with page.expect_event('dialog'):
                    saved.locator('button.primary').click()
                assert profiles()[0]['params']['max_requests_per_poll'] == 3
                page.set_viewport_size({'width': 390, 'height': 844})
                saved.locator('[name=event_vocabulary_version]').select_option('legacy-v1')
                tiers = saved.locator('[name=event_vocabulary_tiers]').evaluate('(s) => [...s.selectedOptions].map(o => o.value)')
                assert tiers == ['core'], 'Legacy retained unsupported experimental tiers'
                saved.locator('[data-event-vocabulary]').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), 'Mobile vocabulary overflow'
                page.set_viewport_size({'width': 1440, 'height': 1000})
                print('PASS stage 2: legacy defaults, splitting/filter retention, budgets, cancel, save/reload, desktop/mobile')

                # Stage 3: country suggestions, explicit conflict resolution and immutable approval.
                form = open_ingestion()
                form.locator('[name=name]').fill('Disposable translation fixture')
                form.locator('[name=keywords]').fill('Baltic Sea')
                tick(form, 'event_presets', 'Cyber')
                tick(form, 'coverage_countries', 'Denmark')
                tick(form, 'nc_languages', 'English')
                form.locator('[name=multilingual_enabled]').check()
                box = form.locator('[data-keyword-translation]')
                expect(box.locator('[data-translation-review]')).to_contain_text('Language filter conflict: da.')
                expect(box.locator('[data-translation-suggestions]')).to_contain_text('da')
                expect(box.locator('[data-translation-generate]')).to_be_disabled()
                languages = form.locator('[name=nc_languages]').evaluate('(s) => [...s.selectedOptions].map(o => o.value)')
                assert languages == ['en'], 'Positive language restrictions were silently broadened'
                box.locator('[data-translation-include]').click()
                expect(box.locator('[data-translation-review]')).not_to_contain_text('Language filter conflict')
                expect(box.locator('[data-translation-row]')).to_have_count(5)
                box.locator('[data-translation-approve]').click()
                expect(box.locator('[data-translation-message]')).to_contain_text('Confirm')
                approve(box)
                approval_id = form.locator('[name=translation_review_id]').input_value()
                assert approval_id
                assert len(profiles()) == 1, 'Approval alone saved/activated a stream'
                approved_before = client.get(f'/api/ingestion/translation-plans/{approval_id}').json()
                plan = preview(form)
                assert plan['request_count'] == 2
                assert [r['translation_language'] for r in plan['requests']] == ['original', 'da']
                assert plan['estimated_credits_per_poll'] == 2
                for phrase in ['Østersøen', 'Danmark', 'cyberangreb']:
                    assert phrase in plan['requests'][1]['parameters']['q'], phrase
                assert 'Baltic Sea' in plan['requests'][0]['parameters']['q']
                accept = True
                form.locator('[data-stream-review-confirm]').check()
                form.locator('[data-stream-actions] button.primary').click()
                page.wait_for_url('**/#/settings/profiles/*')
                translation = next(p for p in profiles() if p['id'] != vocabulary_id)
                assert not translation['enabled']
                assert translation['params']['translation_review_id'] == approval_id
                assert translation['params']['keyword_source_language'] == 'en'
                form = open_ingestion()
                page.reload(wait_until='networkidle')
                saved = page.locator(f'[data-prof="{translation["id"]}"]')
                open_sections(saved)
                box = saved.locator('[data-keyword-translation]')
                expect(box.locator('[data-translation-message]')).to_contain_text('Loaded saved approved snapshot')
                expect(box.locator('[data-translation-text]').first).to_be_disabled()
                expect(saved.locator('[name=keyword_source_language]')).to_have_value('en')
                targets = saved.locator('[name=translation_languages]').evaluate('(s) => [...s.selectedOptions].map(o => o.value)')
                assert targets == ['da']
                assert client.get(f'/api/ingestion/translation-plans/{approval_id}').json()['rows'] == approved_before['rows']

                page.set_viewport_size({'width': 390, 'height': 844})
                box.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), 'Mobile page overflow'
                expect(page.locator('#environment-badge')).to_be_visible()
                expect(box.locator('[data-translation-prepare]')).to_be_visible()
                box.locator('[data-translation-prepare]').click()
                expect(box.locator('[data-translation-confirm]')).to_be_enabled()
                expect(box.locator('[data-translation-review]')).to_contain_text('cache:human-reviewed')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                tick(saved, 'coverage_countries', 'Denmark', False)
                tick(saved, 'coverage_countries', 'Finland')
                expect(box.locator('[data-translation-review]')).to_contain_text('Language filter conflict: fi, sv.')
                expect(saved.locator('[name=translation_review_id]')).to_have_value('')
                targets = saved.locator('[name=translation_languages]').evaluate('(s) => [...s.selectedOptions].map(o => o.value)')
                assert sorted(targets) == ['fi', 'sv'] and len(targets) == 2
                unchanged = next(p for p in profiles() if p['id'] == translation['id'])
                assert unchanged == translation, 'Draft semantics changed the saved stream'
                stale = client.post('/api/profiles/preview-query', json={
                    'name': 'Stale approval', 'params': {**translation['params'], 'coverage_countries': ['FI']},
                })
                assert stale.status_code >= 400, 'Backend accepted a stale approval'

                # Missing phrases are not silently omitted: both manual completion and keep-original.
                page.reload(wait_until='networkidle')
                saved = page.locator(f'[data-prof="{translation["id"]}"]')
                open_sections(saved)
                box = saved.locator('[data-keyword-translation]')
                expect(box.locator('[data-translation-message]')).to_contain_text('Loaded saved approved snapshot')
                saved.locator('[name=keywords]').fill('Unknown test phrase 42')
                expect(box.locator('[data-translation-review]')).to_contain_text('1 missing suggestions')
                approve_failed = box.locator('[data-translation-confirm]')
                approve_failed.check()
                box.locator('[data-translation-approve]').click()
                expect(box.locator('[data-translation-message]')).to_contain_text('one to three')
                missing = box.locator('[data-translation-row]').filter(has_text='Unknown test phrase 42')
                missing.locator('[data-translation-text]').fill('Ukendt testudtryk 42')
                approve(box)
                expect(saved.locator('[data-q]')).to_contain_text('Ukendt testudtryk 42')
                saved.locator('[name=keywords]').fill('Unmapped literal 43')
                expect(box.locator('[data-translation-review]')).to_contain_text('1 missing suggestions')
                missing = box.locator('[data-translation-row]').filter(has_text='Unmapped literal 43')
                missing.locator('[data-translation-keep]').check()
                approve(box)
                expect(saved.locator('[data-q]')).to_contain_text('Unmapped literal 43')
                assert next(p for p in profiles() if p['id'] == translation['id']) == translation
                saved.locator('[name=nc_query]').fill('(ports OR shipping)')
                expect(box.locator('[data-translation-message]')).to_contain_text('Advanced query')
                expect(saved.locator('[name=translation_review_id]')).to_have_value('')
                print('PASS stage 3: suggestions, conflicts, approval, lanes, cache, save/reload, invalidation, missing rows, desktop/mobile')

                assert not any(path.endswith('/generate') for _, path in api_requests)
                assert not provider_attempts and not external_provider_requests
                assert not errors, errors
                with session_scope() as s:
                    assert s.scalar(select(func.count()).select_from(Article)) == 0
                    assert s.scalar(select(func.count()).select_from(SourceProfile)) == 2
                    reviews = s.scalar(select(func.count()).select_from(KeywordTranslationReview))
                print(json.dumps({'passed': True, 'real_api_and_ui': True, 'disposable_database': True,
                                  'fixture_reviews': reviews, 'provider_calls': 0, 'page_errors': errors}))
            finally:
                browser.close()
        engine.dispose()


if __name__ == '__main__':
    main()

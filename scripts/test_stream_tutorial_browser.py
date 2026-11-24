#!/usr/bin/env python3
"""Offline guided-stream acceptance. Playwright setup: see test_stages_browser.py.

Run: python scripts/test_stream_tutorial_browser.py
Real UI/API with a temporary database; no deployed stack or provider access used.
Optional INTEL_TUTORIAL_SCREENSHOT_DIR stores screenshots of synthetic fixtures.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://intel-tutorial-fixture.test'


def main():
    subprocess.run([str(ROOT / 'scripts/development.sh'), 'check'], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='intel-tutorial-') as directory:
        os.environ.update(DATABASE_URL=f'sqlite:///{directory}/fixture.db', APP_ENVIRONMENT='development', APP_PASSWORD='',
                          ANTHROPIC_API_KEY='', NEWSCATCHER_API_KEY='', KEYWORD_TRANSLATION_ALLOW_LIVE='false',
                          FETCH_ARTICLE_TEXT='false', GDELT_FALLBACK_TO_NEWSCATCHER='false')
        sys.path.insert(0, str(ROOT / 'backend'))
        from fastapi.testclient import TestClient
        from playwright.sync_api import expect, sync_playwright
        from sqlalchemy import func, select
        from app.db import engine, session_scope
        from app.main import app
        from app.models import Article

        calls, errors, forbidden = [], [], []
        def blocked(*args, **kwargs):
            forbidden.append('provider transport'); raise AssertionError('No provider calls permitted')
        with patch('requests.sessions.Session.request', side_effect=blocked), \
             patch('httpx.HTTPTransport.handle_request', side_effect=blocked), \
             TestClient(app, base_url=BASE) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                accept = False
                dialogs = []
                def on_dialog(dialog):
                    dialogs.append(dialog.message)
                    dialog.accept() if accept else dialog.dismiss()
                page.on('dialog', on_dialog)
                def serve(route):
                    request = route.request; url = urlsplit(request.url)
                    if url.netloc != 'intel-tutorial-fixture.test':
                        if 'anthropic' in url.netloc or 'newscatcher' in url.netloc: forbidden.append(request.url)
                        route.abort(); return
                    if url.path.startswith('/api/'):
                        calls.append((request.method, url.path, request.post_data))
                    response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                        content=request.post_data_buffer, headers={k:v for k,v in request.headers.items() if k not in {'host','content-length'}})
                    route.fulfill(status=response.status_code, body=response.content,
                        headers={k:v for k,v in response.headers.items() if k not in {'content-length','content-encoding','transfer-encoding'}})
                page.route('**/*', serve)
                def profiles(): return client.get('/api/profiles').json()
                def tick(scope, name, label):
                    picker=scope.locator(f'select[name="{name}"] + section.multi-picker')
                    picker.locator('input[type=search]').fill(label)
                    picker.get_by_role('checkbox', name=label, exact=True).check()
                def open_manual_section(control):
                    control.evaluate('(el) => {for(let p=el.parentElement;p;p=p.parentElement) if(p.tagName==="DETAILS")p.open=true;}')
                def start():
                    page.goto(BASE + '/#/ingestion', wait_until='networkidle')
                    expect(page.locator('#environment-badge')).to_have_text('DEVELOPMENT')
                    form=page.locator('#new-prof'); expect(form.locator('[data-stream-progress]')).to_have_text('Step 1 of 6')
                    return form
                def next_step(form, number):
                    form.locator('[data-stream-next]').click()
                    expect(form.locator('[data-stream-progress]')).to_have_text(f'Step {number} of 6')
                def screenshot(name):
                    if os.environ.get('INTEL_TUTORIAL_SCREENSHOT_DIR'):
                        target=Path(os.environ['INTEL_TUTORIAL_SCREENSHOT_DIR']);target.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(target/name), full_page=True)

                form=start()
                assert form.locator('[data-stream-step]:visible').count()==1
                expect(form.locator('[name=source]')).not_to_be_visible()
                expect(form.locator('[data-stream-actions]')).not_to_be_visible()
                form.locator('[data-stream-next]').click()  # missing name cannot advance
                expect(form.locator('[data-stream-progress]')).to_have_text('Step 1 of 6')
                form.locator('[name=name]').fill('Ports & security <fixture>')
                form.locator('[name=keywords]').fill('ports')
                form.locator('[name=exclude_keywords]').fill('sport')
                next_step(form,2);tick(form,'coverage_countries','Denmark')
                form.locator('[data-stream-back]').click()
                expect(form.locator('[name=keywords]')).to_have_value('ports')
                next_step(form,2)
                assert form.locator('[name=coverage_countries]').evaluate('(s)=>[...s.selectedOptions].map(o=>o.value)')==['DK']
                next_step(form,3);tick(form,'event_presets','Cyber')
                screenshot('tutorial-desktop.png')
                form.locator('[data-stream-mode]').click()
                endpoint=form.locator('[name=nc_endpoint]');open_manual_section(endpoint);endpoint.select_option('articles')
                raw=form.locator('[name=nc_query]');raw.fill('(ports OR shipping)')
                native=form.locator('[name=nc_articles_exclude_duplicates]');open_manual_section(native);native.select_option('false')
                form.locator('[name=nc_articles_word_count_min]').fill('0')
                form.locator('[data-stream-mode]').click()
                expect(form.locator('[data-stream-progress]')).to_have_text('Step 3 of 6')
                next_step(form,4);tick(form,'nc_languages','English');next_step(form,5)
                form.locator('[name=max_requests_per_poll]').fill('3')
                form.locator('[name=max_credits_per_poll]').fill('1')
                next_step(form,6)
                expect(form.locator('[data-stream-preview-status]')).to_contain_text('Preview refused')
                form.locator('[data-stream-actions] button.primary').click()
                assert not profiles()
                form.locator('[data-stream-back]').click()
                form.locator('[name=max_credits_per_poll]').fill('10')
                # Hold a returning preview while editing: it must not become a current approval.
                page.evaluate('''() => {const original=window.fetch; window.holdPreview=true;
                  window.fetch=async (...args)=>{const response=await original(...args);
                    if(window.holdPreview && args[0]==='/api/profiles/preview-query'){
                      window.holdPreview=false;await new Promise(resolve=>window.releasePreview=resolve);
                    }return response;};}''')
                next_step(form,6)
                page.wait_for_function('()=>typeof window.releasePreview === "function"')
                form.locator('[data-stream-back]').click()
                form.locator('[name=interval_minutes]').select_option('180')
                page.evaluate('()=>window.releasePreview()')
                next_step(form,6)
                expect(form.locator('[data-stream-preview-status]')).to_contain_text('Current preview ready')
                summary=form.locator('[data-stream-summary]')
                for text in ['Ports & security <fixture>','sport','Denmark','(ports OR shipping)','false','0','180 minutes','articles']:
                    expect(summary).to_contain_text(text)
                assert summary.locator('fixture').count()==0
                form.locator('[data-stream-actions] button.primary').click()
                expect(form.locator('[data-stream-preview-status]')).to_contain_text('Acknowledge')
                assert not profiles()
                page.set_viewport_size({'width':390,'height':844})
                form.locator('[data-stream-review-confirm]').check()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                screenshot('tutorial-mobile-review.png')
                # Same-frame double submit must not create two streams.
                form.evaluate('(f)=>{f.requestSubmit();f.requestSubmit();}')
                page.wait_for_url('**/#/settings/profiles/*')
                stored=profiles();assert len(stored)==1
                first=stored[0]
                assert not first['enabled'] and first['params']['query']=='(ports OR shipping)'
                assert first['params']['native_filters']['exclude_duplicates'] is False
                assert first['params']['native_filters']['word_count_min']==0
                assert first['interval_minutes']==180
                saved=page.locator(f'[data-prof="{first["id"]}"]')
                expect(saved).to_be_visible()
                assert saved.locator('[data-profile-section]').count()>=6
                assert not saved.locator('[data-stream-step="4"]').evaluate('(d)=>d.open')
                expect(saved.get_by_role('link',name='Next: guided dashboard setup')).to_be_visible()
                page.reload(wait_until='networkidle')
                assert profiles()==stored
                print('PASS guided stream: progressive steps, Back/Next, advanced round-trip, full review, stale previews, paused single save, manual landing, mobile')

                # Guided multilingual path: conflict and approval cannot be skipped.
                page.set_viewport_size({'width':1440,'height':1000})
                form=start();form.locator('[name=name]').fill('Reviewed language fixture')
                form.locator('[name=keywords]').fill('Baltic Sea')
                next_step(form,2);tick(form,'coverage_countries','Denmark')
                next_step(form,3);tick(form,'event_presets','Cyber');next_step(form,4)
                tick(form,'nc_languages','English');form.locator('[name=multilingual_enabled]').check()
                box=form.locator('[data-keyword-translation]')
                expect(box.locator('[data-translation-review]')).to_contain_text('Language filter conflict: da.')
                expect(box.locator('[data-translation-generate]')).to_be_disabled()
                form.locator('[data-stream-next]').click()
                expect(form.locator('[data-stream-message]')).to_contain_text('Review and approve')
                box.locator('[data-translation-include]').click()
                expect(box.locator('[data-translation-row]')).to_have_count(5)
                expect(box.locator('[data-translation-review]')).not_to_contain_text('Language filter conflict')
                box.locator('[data-translation-confirm]').check()
                box.locator('[data-translation-approve]').click()
                expect(box.locator('[data-translation-message]')).to_contain_text('Approved, not saved')
                approval=form.locator('[name=translation_review_id]').input_value();assert approval
                form.locator('[data-stream-mode]').click();form.locator('[data-stream-mode]').click()
                expect(form.locator('[name=translation_review_id]')).to_have_value(approval)
                next_step(form,5);form.locator('[name=max_requests_per_poll]').fill('2')
                form.locator('[name=max_credits_per_poll]').fill('2');next_step(form,6)
                expect(form.locator('[data-stream-preview-status]')).to_contain_text('Current preview ready')
                expect(form.locator('[data-q]')).to_contain_text('lane: da')
                form.locator('[data-stream-review-confirm]').check()
                with page.expect_event('dialog'):
                    form.locator('[data-stream-actions] button.primary').click()
                assert len(profiles())==1 and dialogs
                expect(form.locator('[name=translation_review_id]')).to_have_value(approval)
                accept=True
                form.locator('[data-stream-actions] button.primary').click()
                page.wait_for_url('**/#/settings/profiles/*')
                second=next(p for p in profiles() if p['id']!=first['id'])
                assert not second['enabled'] and second['params']['translation_review_id']==approval
                # New unsaved drafts are not restored by reload; existing streams are unchanged.
                form=start();form.locator('[name=name]').fill('Not saved')
                page.reload(wait_until='networkidle')
                expect(page.locator('#new-prof [name=name]')).to_have_value('')
                assert len(profiles())==2
                assert len([c for c in calls if c[0]=='POST' and c[1]=='/api/profiles'])==2
                assert not any(c[1].endswith('/generate') or c[1].endswith('/run') for c in calls)
                assert not errors and not forbidden,(errors,forbidden)
                with session_scope() as db: assert db.scalar(select(func.count()).select_from(Article))==0
                print('PASS guided multilingual: explicit conflict resolution/approval, snapshot retained through mode switches, experimental cancel/confirm, no live calls')
            finally: browser.close()
        engine.dispose()


if __name__=='__main__':
    main()

"""Shared logo upload/serve/remove and branded HTML export. No external calls."""
import base64
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import PirSet, Summary, utcnow
from app import branding

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32


def data_url(raw, mime='image/png'):
    return f'data:{mime};base64,' + base64.b64encode(raw).decode()


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear(); self.client.close(); self.db.close(); self.engine.dispose()

    def test_upload_serve_meta_and_remove(self):
        self.assertFalse(self.client.get('/api/branding').json()['has_logo'])
        self.assertEqual(self.client.get('/api/branding/logo').status_code, 404)
        saved = self.client.put('/api/branding/logo', json={'data_url': data_url(PNG)})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()['has_logo'])
        served = self.client.get('/api/branding/logo')
        self.assertEqual(served.content, PNG)
        self.assertEqual(served.headers['content-type'], 'image/png')
        self.assertEqual(served.headers['x-content-type-options'], 'nosniff')
        self.assertIn('sandbox', served.headers['content-security-policy'])
        self.assertTrue(self.client.get('/api/meta').json()['branding']['has_logo'])
        self.assertFalse(self.client.delete('/api/branding/logo').json()['has_logo'])
        self.assertEqual(self.client.get('/api/branding/logo').status_code, 404)

    def test_type_detected_from_bytes_not_declared_mime(self):
        saved = self.client.put('/api/branding/logo', json={'data_url': data_url(JPEG, 'image/png')}).json()
        self.assertEqual(saved['mime'], 'image/jpeg')

    def test_rejects_svg_html_oversize_and_invalid_base64(self):
        for raw in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', b'<html></html>' * 5):
            r = self.client.put('/api/branding/logo', json={'data_url': data_url(raw, 'image/svg+xml')})
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.put('/api/branding/logo', json={'data_url': 'data:image/png;base64,@@@notbase64@@@'}).status_code, 400)
        big = PNG + b'\x00' * branding.MAX_BYTES
        self.assertIn(self.client.put('/api/branding/logo', json={'data_url': data_url(big)}).status_code, (400, 422))
        self.assertFalse(self.client.get('/api/branding').json()['has_logo'])

    def test_html_export_embeds_logo_header_and_csp_allows_data_images_only(self):
        self.client.put('/api/branding/logo', json={'data_url': data_url(PNG)})
        dashboard = PirSet(name='Baltic <Watch>'); self.db.add(dashboard); self.db.flush()
        summary = Summary(set_id=dashboard.id, period_label='Last 7 days', period_start=utcnow() - timedelta(days=7),
                          period_end=utcnow(), status='done', content='## Key judgments\nNothing.', references={})
        self.db.add(summary); self.db.commit()
        r = self.client.get(f'/api/summaries/{summary.id}/export?format=html')
        self.assertEqual(r.status_code, 200)
        self.assertIn('class="report-header"', r.text)
        self.assertIn('src="data:image/png;base64,', r.text)
        self.assertIn('Baltic &lt;Watch&gt;', r.text)
        self.assertIn("img-src data:", r.headers['content-security-policy'])
        self.assertIn("default-src 'none'", r.headers['content-security-policy'])
        md = self.client.get(f'/api/summaries/{summary.id}/export?format=md').text
        self.assertNotIn('base64', md)


class AppNameTests(BrandingTests):
    def test_default_save_validate_reset_and_logo_removal_keeps_name(self):
        self.assertEqual(self.client.get('/api/branding').json()['name']['text'], 'Intel Ingest')
        body = {'text': '  Nordic   Watch ', 'font': 'serif', 'size': 20, 'weight': 700, 'italic': True,
                'transform': 'uppercase', 'spacing': 0.1, 'color': 'accent', 'show_mark': False}
        saved = self.client.put('/api/branding/name', json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['name']['text'], 'Nordic Watch')
        self.assertEqual(self.client.get('/api/meta').json()['branding']['name']['font'], 'serif')
        for bad in ({'font': 'url(https://evil.example/f.woff)'}, {'size': 99}, {'weight': 900}, {'color': 'red; x'},
                    {'text': ''}, {'text': 'x' * 61}, {'transform': 'none;background:red'}):
            self.assertEqual(self.client.put('/api/branding/name', json={**body, **bad}).status_code, 422, bad)
        self.client.put('/api/branding/logo', json={'data_url': data_url(PNG)})
        self.client.delete('/api/branding/logo')
        self.assertEqual(self.client.get('/api/branding').json()['name']['text'], 'Nordic Watch')
        self.assertEqual(self.client.delete('/api/branding/name').json()['name']['text'], 'Intel Ingest')

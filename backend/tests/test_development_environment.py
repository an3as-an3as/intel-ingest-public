"""Development identity and fail-closed environment boundary checks; no Docker needed."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from app.config import Settings
from app.main import index

_spec = importlib.util.spec_from_file_location(
    'development_guard', Path(__file__).resolve().parents[2] / 'scripts' / 'check_development.py')
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def safe_config():
    app = {
        'image': 'intel-ingest-dev:local', 'networks': {'default': None},
        'environment': {'APP_ENVIRONMENT': 'development', 'ANTHROPIC_API_KEY': '',
                        'NEWSCATCHER_API_KEY': '', 'FETCH_ARTICLE_TEXT': 'false', 'KEYWORD_TRANSLATION_ALLOW_LIVE': 'false',
                        'DATABASE_URL': 'postgresql+psycopg://intel_dev:fixture-only@db:5432/intel_dev'},
    }
    worker = copy.deepcopy(app)
    worker['profiles'] = ['worker']
    api = copy.deepcopy(app)
    gateway = {
        'image': 'nginx:1.28-alpine', 'networks': {'default': None, 'edge': None},
        'ports': [{'host_ip': '127.0.0.1', 'target': 8080, 'published': '8081'}],
        'volumes': [{'type': 'bind', 'source': '/fixture/deploy/development-nginx.conf',
                     'target': '/etc/nginx/conf.d/default.conf', 'read_only': True}],
    }
    return {
        'name': 'intel-ingest-dev', 'networks': {'default': {'internal': True}, 'edge': {'internal': False}},
        'volumes': {'pgdata': {'name': 'intel-ingest-dev-pgdata'}},
        'services': {
            'api': api, 'gateway': gateway, 'worker': worker,
            'db': {'networks': {'default': None},
                   'environment': {'POSTGRES_USER': 'intel_dev', 'POSTGRES_DB': 'intel_dev'},
                   'volumes': [{'type': 'volume', 'source': 'pgdata', 'target': '/var/lib/postgresql/data'}]},
            'backend-tests': {'profiles': ['tests'], 'networks': {'default': None}},
            'frontend-tests': {'profiles': ['tests'], 'networks': {'default': None}},
        },
    }


class DevelopmentIsolationTests(unittest.TestCase):
    def test_expected_config_passes(self):
        self.assertEqual(guard.validate_config(safe_config()), [])

    def test_production_project_and_volume_are_rejected(self):
        for key in ('project', 'volume'):
            with self.subTest(key=key):
                config = safe_config()
                if key == 'project':
                    config['name'] = 'intel-ingest'
                else:
                    config['volumes']['pgdata']['name'] = 'intel-ingest_pgdata'
                self.assertTrue(guard.validate_config(config))

    def test_external_networks_and_host_networking_are_rejected(self):
        for key in ('internet', 'additional', 'host'):
            with self.subTest(key=key):
                config = safe_config()
                if key == 'internet':
                    config['networks']['default']['internal'] = False
                elif key == 'additional':
                    config['networks']['production'] = {'external': True}
                else:
                    config['services']['api']['network_mode'] = 'host'
                self.assertTrue(guard.validate_config(config))

    def test_live_credentials_and_wrong_database_are_rejected(self):
        for key in ('ANTHROPIC_API_KEY', 'NEWSCATCHER_API_KEY', 'DATABASE_URL', 'OPENAI_API_KEY',
                    'DEEPSEEK_API_KEY', 'GEMINI_API_KEY', 'OLLAMA_API_KEY', 'OLLAMA_BASE_URL'):
            with self.subTest(key=key):
                config = safe_config()
                config['services']['api']['environment'][key] = (
                    'postgresql+psycopg://intel:fixture-only@db:5432/intel' if key == 'DATABASE_URL' else 'fake-live-key')
                self.assertTrue(guard.validate_config(config))

    def test_production_and_public_bindings_are_rejected(self):
        for changes in ({'published': '8080'}, {'host_ip': '0.0.0.0'}, {'published': '0'}):
            with self.subTest(changes=changes):
                config = safe_config()
                config['services']['gateway']['ports'][0].update(changes)
                self.assertTrue(guard.validate_config(config))

    def test_automatic_worker_and_application_mounts_are_rejected(self):
        config = safe_config()
        config['services']['worker'].pop('profiles')
        self.assertTrue(guard.validate_config(config))
        config = safe_config()
        config['services']['api']['volumes'] = [{'source': '.env', 'target': '/app/.env'}]
        self.assertTrue(guard.validate_config(config))
        config = safe_config()
        config['services']['api']['networks']['edge'] = None
        self.assertTrue(guard.validate_config(config))
        config = safe_config()
        config['services']['api']['environment']['KEYWORD_TRANSLATION_ALLOW_LIVE'] = 'true'
        self.assertTrue(guard.validate_config(config))

    def test_development_badge_and_title_are_server_rendered(self):
        with patch('app.main.get_settings', return_value=Settings(_env_file=None, app_environment='development')):
            html = index().body.decode()
        self.assertIn('id="environment-badge"', html)
        self.assertIn('<title>[DEV] Intel Ingest</title>', html)

    def test_production_page_has_no_development_badge(self):
        with patch('app.main.get_settings', return_value=Settings(_env_file=None, app_environment='production')):
            html = index().body.decode()
        self.assertNotIn('id="environment-badge"', html)
        self.assertIn('<title>Intel Ingest</title>', html)


if __name__ == '__main__':
    unittest.main()

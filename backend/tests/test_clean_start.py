"""Fresh installs stay empty; legacy cleanup is selective; UI modules refresh together."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_PASSWORD'] = ''

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app, _startup, UI_VERSION
from app.models import Article, ArticleProfile, Pir, PirSet, SourceProfile, utcnow
from app.sample_cleanup import PROFILES, SETS, remove_samples


class CleanStartTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def legacy_samples(self):
        for name, source, params in PROFILES:
            self.db.add(SourceProfile(name=name, source=source, params=params, enabled=False))
        for sample in SETS:
            dashboard = PirSet(name=sample['name'], description=sample['description'])
            dashboard.pirs = [Pir(code=code, priority=priority, title=title, question=question, indicators=indicators)
                              for code, priority, title, question, indicators in sample['pirs']]
            self.db.add(dashboard)
        self.db.commit()

    def test_startup_never_creates_samples(self):
        with patch('app.main.init_db', return_value=None):
            _startup()
            _startup()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PirSet)), 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SourceProfile)), 0)
        self.assertEqual(remove_samples(self.db, apply=True)['profiles'], [])

    def test_cleanup_preserves_user_records_and_shared_articles(self):
        self.legacy_samples()
        sample = self.db.scalar(select(SourceProfile).order_by(SourceProfile.id))
        custom = SourceProfile(name='Baltic', source='newscatcher', params={'keywords':['shipping']})
        custom_set = PirSet(name='Baltic Monitor', description='User objective')
        self.db.add_all([custom,custom_set]); self.db.flush()
        def article(name, profile):
            result = Article(url=f'https://example.com/{name}', title=name, title_hash=name,
                             published_at=utcnow(), profile_id=profile.id)
            self.db.add(result); self.db.flush()
            return result
        exclusive = article('sample-only', sample)
        shared = article('shared', sample)
        user = article('user', custom)
        self.db.add_all([ArticleProfile(article_id=shared.id, profile_id=custom.id),
                         ArticleProfile(article_id=exclusive.id, profile_id=sample.id)])
        self.db.commit()
        preview = remove_samples(self.db)
        self.assertFalse(preview['applied'])
        self.assertEqual(preview['exclusive_sample_articles'], 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SourceProfile)), 4)
        result = remove_samples(self.db, apply=True)
        self.db.commit(); self.db.expire_all()
        self.assertEqual(len(result['profiles']), 3)
        self.assertEqual(len(result['dashboards']), 3)
        self.assertEqual(self.db.scalars(select(SourceProfile.name)).all(), ['Baltic'])
        self.assertEqual(self.db.scalars(select(PirSet.name)).all(), ['Baltic Monitor'])
        self.assertEqual(set(self.db.scalars(select(Article.title))), {'shared','user'})
        self.assertIsNone(shared.profile_id)
        self.assertEqual(user.profile_id, custom.id)
        self.assertEqual(remove_samples(self.db, apply=True)['profiles'], [])

    def test_edited_samples_are_preserved(self):
        self.legacy_samples()
        profile = self.db.scalar(select(SourceProfile).order_by(SourceProfile.id))
        profile.params = {**profile.params, 'keywords':['user chosen topic']}
        dashboard = self.db.scalar(select(PirSet).order_by(PirSet.id))
        dashboard.pirs[0].question = 'User edited intelligence requirement'
        self.db.commit()
        result = remove_samples(self.db, apply=True)
        self.db.commit()
        self.assertEqual(len(result['profiles']), 2)
        self.assertEqual(len(result['dashboards']), 2)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SourceProfile)), 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PirSet)), 1)

    def test_asset_version_reaches_imports_and_no_store_headers(self):
        client = TestClient(app)
        page = client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'/static/app.js?v={UI_VERSION}', page.text)
        self.assertIn(f'/static/styles.css?v={UI_VERSION}', page.text)
        script = client.get(f'/static/app.js?v={UI_VERSION}')
        self.assertIn(f'./filters.js?v={UI_VERSION}', script.text)
        self.assertIn(f'./setup.js?v={UI_VERSION}', script.text)
        self.assertIn(f'./wireframe-globe.js?v={UI_VERSION}', script.text)
        self.assertIn(f'./overview.js?v={UI_VERSION}', script.text)
        self.assertIn('id="sidebar-toggle"', page.text)
        self.assertIn('id="dashboard-sidebar"', page.text)
        nested = client.get(f'/static/overview.js?v={UI_VERSION}')
        self.assertIn(f'./wireframe-globe.js?v={UI_VERSION}', nested.text)
        self.assertEqual(client.get('/static/nonexistent.js').status_code, 404)
        filters = client.get(f'/static/filters.js?v={UI_VERSION}')
        self.assertIn("search.type = 'search'", filters.text)
        for response in (page,script,filters):
            self.assertEqual(response.headers['Cache-Control'], 'no-store, max-age=0')
            self.assertEqual(response.headers['X-UI-Version'], UI_VERSION)
        client.close()


if __name__ == '__main__':
    unittest.main()

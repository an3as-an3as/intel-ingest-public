"""Demo data is fictional, offline and only loads into an empty installation."""
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.demo_seed import DASHBOARDS, seed
from app.main import app
from app.models import Article, PirSet, SourceProfile, Summary


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()

    def tearDown(self):
        app.dependency_overrides.clear(); self.db.close(); self.engine.dispose()

    def test_seed_is_fictional_paused_and_renders_in_the_api(self):
        created = seed(self.db, now=datetime.now(timezone.utc))
        self.assertEqual(created['dashboards'], len(DASHBOARDS))
        self.assertTrue(all(a.url.startswith('https://') and '.example/' in a.url for a in self.db.scalars(select(Article))))
        self.assertFalse(any(p.enabled for p in self.db.scalars(select(SourceProfile))))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Summary)), 1)
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            totals = {w: sum(sum(p['count'] for p in d['points']) for d in client.get(f'/api/overview?window={w}').json()['dashboards'])
                      for w in ('24h', '7d', '90d')}
            self.assertTrue(0 < totals['24h'] < totals['7d'] < totals['90d'], totals)
            sid = self.db.scalar(select(PirSet.id))
            self.assertEqual(client.get(f'/api/dashboards/{sid}').status_code, 200)

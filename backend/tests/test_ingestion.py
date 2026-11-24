"""Offline ingestion/configuration regression tests; no provider calls."""
import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_PASSWORD"] = ""

import unittest
from datetime import timedelta
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Article, ArticlePir, ArticleProfile, Pir, PirSet, SourceProfile, Summary, utcnow
from app.pipeline.analytics import pir_stats
from app.pipeline.ingest import is_due, run_profile
from app.pipeline.scope import dashboard_scope
from app.pipeline.summarize import run_summary
from app.sources.base import RawArticle
from app.sources.newscatcher import NewsCatcherSource, build_q


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.dashboard = PirSet(name="Analysis")
        self.db.add(self.dashboard)
        self.db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def create(self, **overrides):
        payload = dict(name="Baltic stream", source="newscatcher", enabled=False,
                       interval_minutes=60, params={"keywords": ["shipping"]}, dashboard_ids=[])
        payload.update(overrides)
        response = self.client.post("/api/profiles", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), payload

    def test_options_preview_and_validation(self):
        options = self.client.get("/api/meta").json()["ingestion_options"]
        self.assertEqual(options["countries"]["FI"], "Finland")
        self.assertEqual(options["languages"]["en"], "English")
        p, payload = self.create(params={"event_presets": ["cyber"], "coverage_countries": ["FI"]})
        query = self.client.post("/api/profiles/preview-query", json=payload).json()["query"]
        self.assertIn("ransomware", query)
        self.assertIn(" AND (Finland)", query)
        for invalid in ({"keywords": []}, {"keywords": "abc"}, {"keywords": ["x"], "event_presets": ["bogus"]},
                        {"keywords": ["x"], "max_records": -1}):
            self.assertEqual(self.client.post("/api/profiles", json={**payload, "params": invalid}).status_code, 422)
        self.assertEqual(self.client.post("/api/profiles", json={**payload, "dashboard_ids": [999]}).status_code, 400)
        self.db.rollback()

    def test_links_update_and_schedule(self):
        p, payload = self.create(dashboard_ids=[self.dashboard.id])
        self.assertEqual(p["dashboard_ids"], [self.dashboard.id])
        self.assertEqual(self.client.post(f'/api/profiles/{p["id"]}/run').status_code, 409)
        for _ in range(2):
            response = self.client.put(f'/api/profiles/{p["id"]}', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
        profile = self.db.get(SourceProfile, p["id"])
        now = utcnow()
        self.assertFalse(is_due(profile, now))
        profile.enabled = True
        profile.last_run_at = now - timedelta(minutes=59)
        self.assertFalse(is_due(profile, now))
        self.assertTrue(is_due(profile, now + timedelta(minutes=1)))
        payload["dashboard_ids"] = []
        self.assertEqual(self.client.put(f'/api/profiles/{p["id"]}', json=payload).json()["dashboard_ids"], [])

    def test_overlapping_streams_and_dashboard_scope(self):
        first, _ = self.create()
        second, _ = self.create(name="Second", dashboard_ids=[self.dashboard.id])
        profiles = [self.db.get(SourceProfile, x["id"]) for x in (first, second)]
        raw = RawArticle(url="https://example.com/news", title="Shipping report", published_at=utcnow())
        with patch("app.pipeline.ingest.SOURCES") as sources:
            sources.get.return_value.fetch.return_value = [raw, RawArticle(
                url="https://other.example.com/copy", title=raw.title, published_at=raw.published_at)]
            self.assertEqual(run_profile(self.db, profiles[0]), 1)
            self.db.commit()
            self.assertEqual(run_profile(self.db, profiles[1]), 0)
            self.db.commit()
            self.assertEqual(run_profile(self.db, profiles[1]), 0)
            self.db.commit()
        article = self.db.scalar(select(Article))
        self.assertEqual(len(self.db.scalars(select(ArticleProfile)).all()), 2)
        result = self.client.get(f'/api/articles?profile_id={second["id"]}').json()
        self.assertEqual(result["total"], 1)
        article.status = "enriched"
        pir = Pir(set_id=self.dashboard.id, code="T1", title="Shipping", question="What changed?")
        self.db.add(pir)
        self.db.flush()
        self.db.add(ArticlePir(article_id=article.id, pir_id=pir.id, score=0.9))
        unrelated = Article(url="https://example.com/other", title="Other", title_hash="other",
                            published_at=utcnow(), status="enriched")
        self.db.add(unrelated)
        self.db.flush()
        self.db.add(ArticlePir(article_id=unrelated.id, pir_id=pir.id, score=0.8))
        self.db.commit()
        dashboard = self.client.get(f'/api/dashboards/{self.dashboard.id}').json()
        self.assertEqual(dashboard["total"], 1)
        self.assertEqual(dashboard["stats"][0]["count"], 1)
        self.assertEqual(pir_stats(self.db, [pir], "7d")[0]["count"], 1)
        self.assertEqual(len(self.db.scalars(select(Article).where(dashboard_scope(self.dashboard.id))).all()), 1)
        summary = Summary(set_id=self.dashboard.id, period_label="Test", period_start=utcnow()-timedelta(days=7), period_end=utcnow())
        self.db.add(summary)
        self.db.commit()

        @contextmanager
        def summary_session():
            yield self.db
            self.db.commit()

        with patch("app.pipeline.summarize.session_scope", summary_session), patch("app.pipeline.summarize.llm.call", return_value="Report") as llm:
            run_summary(summary.id)
        self.assertEqual(summary.status, "done")
        self.assertEqual(summary.article_count, 1)
        self.assertNotIn(f"A{unrelated.id}", summary.references)
        self.assertNotIn("Title: Other", llm.call_args.kwargs["user"])
        # Legacy dashboards without explicit links still see all matched reporting.
        self.db.query(type(profiles[1].dashboard_links[0])).delete()
        self.db.commit()
        self.assertEqual(pir_stats(self.db, [pir], "7d")[0]["count"], 2)

    def test_provider_request_uses_presets_and_native_filters(self):
        source = NewsCatcherSource()
        params = {"keywords": ["shipping"], "event_presets": ["maritime"], "coverage_countries": ["FI"],
                  "source_countries": ["GB"], "languages": ["en"], "max_records": 100}
        settings = SimpleNamespace(newscatcher_api_key="test-only", newscatcher_effort="low")
        response = SimpleNamespace(status_code=200, json=lambda: {"results": []})
        with patch.object(source, "_plan", return_value={"max_articles_per_page": 20}), patch("app.sources.newscatcher._throttle"), patch("app.sources.newscatcher.requests.post", return_value=response) as post:
            source._fetch_news(settings, params, utcnow()-timedelta(hours=1), utcnow())
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["countries"], ["GB"])
        self.assertEqual(body["languages"], ["en"])
        self.assertEqual(body["limit"], 20)
        self.assertIn("Finland", body["q"])
        self.assertIn("maritime", body["q"])
        self.assertNotIn("event_presets", body)

    def test_keyword_query_compatibility(self):
        self.assertEqual(build_q({"keywords": ["shipping", "Red Sea"], "exclude_keywords": ["sport"]}),
                         '(shipping OR "Red Sea") NOT sport')


if __name__ == "__main__":
    unittest.main()

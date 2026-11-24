"""Guided setup persists prompts, links streams and feeds the actual classifier."""
import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_PASSWORD"] = ""

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Article, ArticlePir, ArticleProfile, PirSet, ProfileDashboard, SourceProfile, utcnow
from app.pipeline.classify import enrich_pending


class DashboardSetupTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.engine = engine
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.stream = SourceProfile(name="Configured stream", source="newscatcher", enabled=False,
                                    interval_minutes=60, params={"keywords": ["shipping"]})
        self.other = SourceProfile(name="Other stream", source="newscatcher", enabled=True,
                                   interval_minutes=30, params={"keywords": ["energy"]})
        self.db.add_all([self.stream, self.other])
        self.db.commit()
        self.payload = dict(name="Shipping risk", objective="Support decisions about route safety",
                            geography="Red Sea", actors="Commercial vessels", exclusions="Unrelated exercises",
                            profile_ids=[self.stream.id], reclassify_days=7,
                            questions=[dict(title="Attacks", question="Which attacks disrupt shipping?",
                                            indicators="New attacks, diversions and closures", exclusions="Old incidents", priority=1)])

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def article(self, label, profile=None, status="enriched", days=1):
        article = Article(url=f"https://example.com/{label}", title=label, title_hash=label,
                          published_at=utcnow()-timedelta(days=days), profile_id=(profile or self.stream).id,
                          status=status, description="Shipping report")
        self.db.add(article)
        self.db.commit()
        return article

    def launch(self, payload=None):
        response = self.client.post("/api/dashboard-setup", json=payload or self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preview_is_read_only_and_contains_all_answers(self):
        response = self.client.post("/api/dashboard-setup/preview", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        for text in ("Support decisions", "Red Sea", "Commercial vessels", "Unrelated exercises",
                     "Which attacks", "New attacks", "Old incidents"):
            self.assertIn(text, preview["system_prompt"])
        self.assertFalse(preview["streams"][0]["enabled"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PirSet)), 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ProfileDashboard)), 0)

    def test_launch_scopes_backfill_and_preserves_configuration(self):
        recent = self.article("Recent", status="irrelevant")
        failed = self.article("Failed", status="failed")
        old = self.article("Old", days=20)
        other = self.article("Unrelated", profile=self.other)
        shared = self.article("Shared", profile=self.other)
        self.db.add(ArticleProfile(article_id=shared.id, profile_id=self.stream.id))
        legacy_dashboard = PirSet(name="Already linked")
        self.db.add(legacy_dashboard)
        self.db.flush()
        self.db.add(ProfileDashboard(profile_id=self.stream.id, set_id=legacy_dashboard.id))
        self.db.commit()
        result = self.launch()
        self.assertEqual(result["queued"], 3)
        self.db.expire_all()
        for article in (recent, failed, shared):
            self.assertEqual(article.status, "pending")
        for article in (old, other):
            self.assertEqual(article.status, "enriched")
        self.assertFalse(self.stream.enabled)
        self.assertEqual(self.stream.interval_minutes, 60)
        self.assertEqual(self.stream.params, {"keywords": ["shipping"]})
        self.assertEqual(len(self.stream.dashboard_links), 2)
        status = self.client.get(f'/api/dashboards/{result["set"]["id"]}/processing').json()
        self.assertEqual(status["counts"]["pending"], 3)
        self.assertEqual(status["matched"], 0)

    def test_unique_requirements_and_new_articles_only(self):
        article = self.article("Existing")
        first = self.launch({**self.payload, "reclassify_days": 0})
        second = self.launch({**self.payload, "reclassify_days": 0})
        self.assertEqual(first["queued"], 0)
        self.assertNotEqual(first["set"]["pirs"][0]["code"], second["set"]["pirs"][0]["code"])
        self.db.refresh(article)
        self.assertEqual(article.status, "enriched")

    def test_validation_creates_no_partial_dashboard(self):
        invalid = [dict(profile_ids=[]), dict(profile_ids=[999]), dict(name="   "), dict(objective=" "),
                   dict(questions=[]), dict(questions=[dict(title="Test", question=" ")]), dict(reclassify_days=91)]
        for overrides in invalid:
            response = self.client.post("/api/dashboard-setup", json={**self.payload, **overrides})
            self.assertIn(response.status_code, (400, 422), response.text)
            self.assertEqual(self.db.scalar(select(func.count()).select_from(PirSet)), 0)

    def test_saved_requirements_reach_model_and_populate_dashboard(self):
        article = self.article("New vessel attack", status="pending")
        result = self.launch()
        code = result["set"]["pirs"][0]["code"]
        settings = SimpleNamespace(classify_batch_size=40, fetch_article_text=False, classify_concurrency=1,
                                   classify_model="claude-test-model", classify_effort="low", pir_match_threshold=0.5)
        output = dict(relevant=True, event_type="maritime", region="middle_east", countries=["YE"],
                      location=dict(name=None, lat=None, lon=None, precision="none"), summary="A vessel was attacked.",
                      pir_matches=[dict(pir_code=code, score=0.9, rationale="New attack disrupts shipping.")])
        with patch("app.pipeline.classify.get_settings", return_value=settings), patch("app.pipeline.classify.llm.call_json", return_value=output) as model:
            self.assertEqual(enrich_pending(self.db), 1)
        self.db.commit()
        prompt = model.call_args.kwargs["system"]
        self.assertIn("Which attacks disrupt shipping?", prompt)
        self.assertIn("Red Sea", prompt)
        self.assertIn("Do not match: Old incidents", prompt)
        self.assertIn("New vessel attack", model.call_args.kwargs["user"])
        self.assertIn(code, model.call_args.kwargs["schema"]["properties"]["pir_matches"]["items"]["properties"]["pir_code"]["enum"])
        dashboard = self.client.get(f'/api/dashboards/{result["set"]["id"]}').json()
        self.assertEqual(dashboard["total"], 1)
        self.assertEqual(dashboard["stats"][0]["count"], 1)
        self.assertEqual(dashboard["articles"][0]["pirs"][0]["rationale"], "New attack disrupts shipping.")
        status = self.client.get(f'/api/dashboards/{result["set"]["id"]}/processing').json()
        self.assertEqual(status["matched"], 1)
        self.assertEqual(status["counts"]["enriched"], 1)


if __name__ == "__main__":
    unittest.main()

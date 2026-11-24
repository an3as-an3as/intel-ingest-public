"""Payload regression snapshots generated with production 91b68b2, offline.

No private stream configuration is embedded. Real production profiles are also
compared in the private release rehearsal, without logging their query text.
"""
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from app.sources.newscatcher import build_q, build_requests, query_planner_version
from app.sources.options import EVENT_QUERIES

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
CASES = {
    'search_split': {'endpoint':'search','event_presets':list(EVENT_QUERIES),
                     'coverage_countries':['US','GB','DE','FR','FI','SE','DK','NO','IS','JP','CN','KR','IN','UA']},
    'articles_split': {'endpoint':'articles','event_presets':list(EVENT_QUERIES),
                       'keywords':['coast '*20,'ports '*20], 'languages':['en','fr'],
                       'source_countries':['GB'], 'exclude_keywords':['sports']},
    'duplicates_and_order': {'keywords':['ports','ports','rail terminal'],
                             'event_presets':['cyber','cyber'], 'coverage_countries':['SE','FI','SE']},
    'raw_query': {'query':'(ports OR "rail terminal") NOT sport','event_presets':['maritime']},
    'v3': {'endpoint':'v3','event_presets':['cyber'], 'coverage_countries':['FI','SE'],
           'languages':['en','fi'], 'themes':['test'], 'max_records':300},
    'native': {'event_presets':['armed_conflict'], 'native_filters':{'effort':'high','not_sources':['example.test']},
               'max_records':30},
}
# Filled with canonical production compiler SHA-256s; see release rehearsal report.
GOLDENS = {
    'search_split':'a98e6edb2de6e4f1eb3283595401fcbab4978cc3ab57b1d673b7bd1c58e20d0f',
    'articles_split':'cc28e5d9e4e94aae1bfc4b68a97326a2df3f85e66ac7f464109e68a1862dc2dd',
    'duplicates_and_order':'29a75ff63294e88198a89f85bc88591c7acaf14e5756dd403c70e7794309432e',
    'raw_query':'b5d5ffabe140dd69dfef8f708f33a2e341583cf73132f386fefadd19636832f3',
    'v3':'5374804c8385162d74b76c959eda6b10664638c60b56af9f035fa16b0719a572',
    'native':'0a62ed972775814f8fe4c487949f1a487332c3a36b3883f4e55dbd22e6dcb627',
}


def payload_hash(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class LegacyQueryPlannerTests(unittest.TestCase):
    def test_exact_production_payloads(self):
        self.assertEqual(set(GOLDENS), set(CASES))
        for name, params in CASES.items():
            with self.subTest(name=name):
                version = 'v3' if params.get('endpoint') == 'v3' else 'news'
                parts = build_requests(params, NOW-timedelta(hours=24), NOW, api_version=version,
                                       effort='low', plan={'max_articles_per_page':100})
                self.assertEqual(payload_hash(parts), GOLDENS[name])
                explicit = build_requests({**params, 'query_planner_version':'legacy-v1'},
                                          NOW-timedelta(hours=24), NOW, api_version=version,
                                          effort='low', plan={'max_articles_per_page':100})
                self.assertEqual(parts, explicit)

    def test_missing_version_keeps_order_and_duplicates(self):
        self.assertEqual(query_planner_version({}), 'legacy-v1')
        query = build_q({'keywords':['ports','ports'], 'coverage_countries':['SE','FI']})
        self.assertEqual(query, '(ports OR ports) AND (Sweden OR Finland)')
        self.assertEqual(build_q({'keywords':['OR']}), 'OR')  # Frozen legacy syntax, not a new default.
        self.assertEqual(build_q({'keywords':['OR'], 'query_planner_version':'bounded-v1'}), '"OR"')

    def test_enhanced_features_cannot_silently_use_legacy_planner(self):
        for extra in ({'coverage_regions':['europe']}, {'event_vocabulary_version':'optimized-v1'},
                      {'multilingual_enabled':True}):
            self.assertEqual(query_planner_version(extra), 'bounded-v1')
            with self.assertRaises(ValueError):
                query_planner_version({**extra, 'query_planner_version':'legacy-v1'})
        for version in ('unknown', None, [], {}):
            with self.subTest(version=version), self.assertRaises(ValueError):
                query_planner_version({'query_planner_version':version})

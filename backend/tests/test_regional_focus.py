"""Regional coverage and single-list baseline integration; no provider calls."""
import unittest
from datetime import datetime, timedelta, timezone

from app.sources.regions import REGIONS, coverage_countries
from app.sources.options import COUNTRIES, ingestion_options
from app.sources.event_vocabulary import catalog, selected_terms, settings
from app.sources.newscatcher import build_requests, build_q


class RegionalFocusTests(unittest.TestCase):
    def test_region_codes_and_union(self):
        for region in REGIONS.values():
            self.assertTrue(set(region['countries']) <= set(COUNTRIES))
        result = coverage_countries({'coverage_regions': ['europe', 'asia'], 'coverage_countries': ['GB', 'US']})
        self.assertEqual(len(result), len(set(result)))
        self.assertTrue({'GB', 'US', 'JP', 'UA'} <= set(result))
        self.assertEqual(coverage_countries({}), [])

    def test_invalid_region(self):
        for value in ['europe', ['unknown'], [5]]:
            with self.assertRaises(ValueError):
                coverage_countries({'coverage_regions': value})
        with self.assertRaises(ValueError):
            coverage_countries({'coverage_regions': ['asia'], 'coverage_region_version': 'unknown'})

    def test_query_keeps_events_and_regional_country_names(self):
        params = {'event_presets': ['armed_conflict'], 'event_vocabulary_version': 'optimized-v1',
                  'coverage_regions': ['europe', 'asia'], 'nc_endpoint': 'articles'}
        query = build_q(params)
        self.assertIn('airstrike', query)
        self.assertIn('Japan', query)
        self.assertIn('Ukraine', query)
        self.assertIn('AND', query)
        now = datetime.now(timezone.utc)
        # Full compiler must preserve all terms via bounded splitting, not truncate.
        parts = build_requests(params, now - timedelta(hours=1), now, api_version='news')
        combined = ' '.join(body['q'] for _, body in parts)
        for country in coverage_countries(params):
            self.assertIn(COUNTRIES[country], combined)
        self.assertLessEqual(len(parts), 16)
        self.assertEqual(ingestion_options()['coverage_regions']['asia'], 'Asia')

    def test_disabled_translation_suggestions_do_not_block_region_preview(self):
        from app.main import ProfileIn
        from app.sources.keyword_translation import suggested_languages, target_languages
        params = {'event_presets':['armed_conflict'], 'coverage_regions':['europe','asia'],
                  'event_vocabulary_version':'optimized-v1', 'multilingual_enabled':False}
        params['translation_languages'] = suggested_languages(coverage_countries(params))
        self.assertGreater(len(params['translation_languages']), 8)
        ProfileIn(name='Regional coverage', params=params)
        with self.assertRaises(ValueError):
            target_languages({**params, 'multilingual_enabled':True})

    def test_single_tier_complete_baseline(self):
        self.assertEqual(list(catalog()['optimized-v1']['tiers']), ['core'])
        for event in ingestion_options()['event_presets']:
            self.assertTrue(selected_terms({'event_presets': [event], 'event_vocabulary_version': 'optimized-v1'}))
        with self.assertRaises(ValueError):
            settings({'event_vocabulary_version': 'optimized-v1', 'event_vocabulary_tiers': ['discovery']})
        self.assertEqual(settings({})[0], 'legacy-v1')

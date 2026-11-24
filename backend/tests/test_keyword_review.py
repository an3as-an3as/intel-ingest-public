"""Keyword-review sampling/preparation is offline and preserves source/annotations."""
from contextlib import closing
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/prepare_keyword_review.py'
spec=importlib.util.spec_from_file_location('keyword_review_prep',SCRIPT)
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


class KeywordReviewTests(unittest.TestCase):
    def articles(self):
        return {f'https://example.test/{i}':{'title':'Ransomware incident' if i<3 else f'Control {i}',
            'description':'Returned evidence','language':['en','da','sv'][i%3],'publisher':'example.test'} for i in range(30)}

    def test_literal_screen_is_casefolded_metadata_only(self):
        self.assertEqual(review.literal_terms({'title':'RANSOMWARE incident','description':'Data breach'},['ransomware','data breach']),['ransomware','data breach'])
        self.assertEqual(review.literal_terms({'title':'Cyber attack','description':''},['cyberattack']),[])

    def test_sample_retains_hits_stratifies_controls_and_is_order_independent(self):
        articles=self.articles();baseline=set(list(articles)[:15]);terms=['ransomware']
        chosen,hits,strata=review.select_sample(articles,terms,baseline,15,'fixed-seed')
        self.assertEqual(len(chosen),15);self.assertEqual(len(hits),3);self.assertTrue(hits<=chosen)
        self.assertTrue(all(s['sampled_controls']>0 for s in strata))
        self.assertEqual(sum(s['sampled_controls'] for s in strata),12)
        self.assertEqual(sum(s['available_controls'] for s in strata),27)
        again=review.select_sample(dict(reversed(list(articles.items()))),terms,baseline,15,'fixed-seed')
        self.assertEqual((chosen,hits,strata),again)
        self.assertEqual(sum(s['sampled_controls']*s['control_population_weight'] for s in strata),27)

    def test_too_small_or_oversized_sample_is_rejected(self):
        for size in (2,4,31):
            with self.assertRaises(ValueError):review.select_sample(self.articles(),['ransomware'],set(),size,'seed')

    def test_preparation_uses_only_local_preview_and_never_changes_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pilot_id='b'*32
            folder=root/'data/pilots'/pilot_id;folder.mkdir(parents=True)
            source=root/'backend/app/sources';source.mkdir(parents=True)
            (source/'event_vocabularies.json').write_text(json.dumps({'legacy-v1':{'events':{'cyber':{'core':['ransomware']}}}}))
            articles=self.articles()
            first=next(iter(articles));articles[first]['title']='<script>malicious</script> ransomware'
            database=folder/'pilot.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript('''CREATE TABLE pilot_meta(key TEXT,value TEXT);
                  CREATE TABLE pilot_attempts(id INTEGER,variant TEXT);
                  CREATE TABLE pilot_memberships(attempt_id INTEGER,url TEXT);
                  CREATE TABLE pilot_articles(url TEXT,article_json TEXT);''')
                db.execute('INSERT INTO pilot_meta VALUES (?,?)',('plan',json.dumps({'variants':[{'name':'baseline'},{'name':'multi'}]})))
                db.execute('INSERT INTO pilot_attempts VALUES (?,?)',(1,'baseline'))
                for url,article in articles.items():db.execute('INSERT INTO pilot_articles VALUES (?,?)',(url,json.dumps(article)))
                for url in list(articles)[:15]:db.execute('INSERT INTO pilot_memberships VALUES (?,?)',(1,url))
                db.commit()
            before=database.read_bytes()
            original={'id':2,'name':'Fixture','source':'newscatcher','enabled':False,'interval_minutes':180,'dashboard_ids':[],
                'params':{'keywords':['Objective sentence'],'event_presets':['cyber'],'coverage_countries':['DK'],
                'languages':['en','da'],'max_records':50,'event_vocabulary_version':'expanded-v1','multilingual_enabled':True,
                'translation_review_id':'private-review'}}
            calls=[]
            def local(path,body=None):
                calls.append((path,copy.deepcopy(body)))
                if path=='/api/meta':return {'environment':'development','newscatcher_configured':False,'claude_configured':False}
                if path=='/api/profiles':return [copy.deepcopy(original)]
                self.assertEqual(path,'/api/profiles/preview-query')
                self.assertFalse(body['enabled']);self.assertEqual(body['params']['keywords'],[])
                self.assertFalse(body['params']['multilingual_enabled'])
                self.assertNotIn('translation_review_id',body['params'])
                self.assertEqual(body['params']['event_vocabulary_version'],'legacy-v1')
                return {'request_count':1,'estimated_credits_per_poll':1,'requests':[]}
            with patch.object(review,'ROOT',root),patch.object(review,'local_json',side_effect=local):
                result,manifest=review.prepare(pilot_id,2,'cyber',15)
                self.assertEqual(database.read_bytes(),before)
                self.assertEqual(manifest['sample_size'],15);self.assertEqual(manifest['literal_metadata_hits'],3)
                self.assertEqual(manifest['paid_requests_made'],0)
                page=(result/'review-sample.html').read_text()
                self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)
                self.assertIn('not a fresh Legacy search',page)
                with (result/'review-sample.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
                self.assertEqual(len(rows),15)
                self.assertTrue(all(not r['cyber_relevance'] and not r['geography_relevance'] for r in rows))
                (result/'review-sample.csv').write_text('User labels retained')
                with self.assertRaises(FileExistsError):review.prepare(pilot_id,2,'cyber',15)
                self.assertEqual((result/'review-sample.csv').read_text(),'User labels retained')
            self.assertTrue(all(path in {'/api/meta','/api/profiles','/api/profiles/preview-query'} for path,_ in calls))
            self.assertEqual(original['params']['keywords'],['Objective sentence'])

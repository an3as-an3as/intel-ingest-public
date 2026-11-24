"""Private offline review export: no providers/app database, safe HTML and CSV."""
from contextlib import closing
import csv
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/export_pilot_review.py'
spec=importlib.util.spec_from_file_location('pilot_review_export',SCRIPT)
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


class PilotReviewTests(unittest.TestCase):
    def fixture(self):
        return {
            'https://example.test/shared':{'title':'Shared <script>alert(1)</script>', 'language':'en','publisher':'example.test','description':'<img src=x onerror=bad()>','published_at':''},
            'https://local.test/new':{'title':'=HYPERLINK("evil")','language':'da','publisher':'local.test','description':'Returned excerpt'},
        }

    def test_html_is_self_contained_escaped_and_cohorts_are_clear(self):
        articles=self.fixture()
        document,text=review.render(articles,{u:{'baseline','multilingual'} for u in articles},{u:{'original'} for u in articles},{'https://example.test/shared'})
        self.assertIn('Additional to the baseline — 1 URLs',document)
        self.assertIn('Found by the baseline — 1 URLs',document)
        self.assertIn('default-src',document)
        self.assertIn('not classified',document)
        self.assertIn('articles-review.csv',document)
        self.assertNotIn('<script>',document);self.assertNotIn('<img',document)
        self.assertIn('&lt;script&gt;',document)
        self.assertIn('rel="noopener noreferrer"',document)
        rows=list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows),2)
        self.assertEqual({r['cohort'] for r in rows},{'baseline','additional'})
        self.assertTrue(all(r['review_id'].startswith('a-') for r in rows))
        self.assertTrue(all(r['review_label']==r['reviewer_notes']=='' for r in rows))

    def test_unsafe_links_are_never_rendered_as_navigation(self):
        for url in ('javascript:alert(1)','data:text/html,bad','https://user:password@example.test'):
            self.assertIsNone(review.safe_url(url))
        self.assertEqual(review.safe_url('https://example.test/report'),'https://example.test/report')

    def test_csv_formula_prefixes_are_defanged_without_altering_normal_urls(self):
        for value in ('=HYPERLINK("evil")',' +SUM(1,1)','-1+1','@SUM(1)','\tformula','\nformula'):
            self.assertTrue(review.csv_cell(value).startswith("'"))
        self.assertEqual(review.csv_cell('https://example.test/report'),'https://example.test/report')

    def test_export_is_read_only_and_refuses_to_overwrite_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pilot_id='a'*32
            folder=root/'data/pilots'/pilot_id;folder.mkdir(parents=True)
            database=folder/'pilot.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript('''CREATE TABLE pilot_meta(key TEXT,value TEXT);
                    CREATE TABLE pilot_attempts(id INTEGER,variant TEXT,request_json TEXT);
                    CREATE TABLE pilot_memberships(attempt_id INTEGER,url TEXT);
                    CREATE TABLE pilot_articles(url TEXT,article_json TEXT);''')
                db.execute('INSERT INTO pilot_meta VALUES (?,?)',('plan',json.dumps({'variants':[{'name':'baseline'},{'name':'multilingual'}]})))
                db.execute('INSERT INTO pilot_attempts VALUES (?,?,?)',(1,'baseline',json.dumps({'language_lane':'original'})))
                for url,article in self.fixture().items():
                    db.execute('INSERT INTO pilot_articles VALUES (?,?)',(url,json.dumps(article)))
                db.execute('INSERT INTO pilot_memberships VALUES (?,?)',(1,'https://example.test/shared'));db.commit()
            before=database.read_bytes()
            with patch.object(review,'ROOT',root):
                files=review.export(pilot_id)
                self.assertEqual(database.read_bytes(),before)
                self.assertTrue(all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in files))
                files[1].write_text('Human annotations retained')
                with self.assertRaises(ValueError):review.export(pilot_id)
                self.assertEqual(files[1].read_text(),'Human annotations retained')

    def test_invalid_ids_do_not_open_arbitrary_databases(self):
        for value in ('../production','not-an-id','a'*31):
            with self.assertRaises(ValueError):review.export(value)

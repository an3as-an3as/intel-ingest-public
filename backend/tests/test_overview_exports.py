"""Overview counts/scope and portable summary exports: no model or external API calls."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_PASSWORD'] = ''

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Article, ArticlePir, ArticleProfile, Pir, PirSet, ProfileDashboard, SourceProfile, Summary

AT = datetime(2026,5,1,12,tzinfo=timezone.utc)


class OverviewExportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine,expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda:self.db
        self.client = TestClient(app)
        self.clock = patch('app.main.now',return_value=AT);self.clock.start()
        self.a = PirSet(name='Dashboard A'); self.b = PirSet(name='Dashboard B')
        self.pa = SourceProfile(name='A stream',source='newscatcher',params={})
        self.pb = SourceProfile(name='B stream',source='newscatcher',params={})
        self.db.add_all([self.a,self.b,self.pa,self.pb]);self.db.flush()
        self.a1 = Pir(set_id=self.a.id,code='A1',title='One',question='One')
        self.a2 = Pir(set_id=self.a.id,code='A2',title='Two',question='Two')
        self.inactive = Pir(set_id=self.a.id,code='A3',title='Inactive',question='Inactive',active=False)
        self.b1 = Pir(set_id=self.b.id,code='B1',title='B',question='B')
        self.db.add_all([self.a1,self.a2,self.inactive,self.b1]);self.db.flush()
        self.db.add_all([ProfileDashboard(profile_id=self.pa.id,set_id=self.a.id),ProfileDashboard(profile_id=self.pb.id,set_id=self.b.id)])
        self.db.commit()

    def tearDown(self):
        self.clock.stop();app.dependency_overrides.clear()
        self.client.close();self.db.close();self.engine.dispose()

    def article(self,name,days,profile,pirs,**kwargs):
        article = Article(url=f'https://example.com/{name}',title=name,title_hash=name,published_at=AT-timedelta(days=days),
                          status='enriched',profile_id=profile.id,lat=10,lon=20,**kwargs)
        self.db.add(article);self.db.flush()
        for pir in pirs:self.db.add(ArticlePir(article_id=article.id,pir_id=pir.id,score=.9))
        return article

    def data(self):
        shared = self.article('Shared',1,self.pa,[self.a1,self.a2,self.b1])
        self.db.add(ArticleProfile(article_id=shared.id,profile_id=self.pb.id))
        self.article('A current',2,self.pa,[self.a1])
        unlocated = self.article('Unlocated',3,self.pa,[self.a1]);unlocated.lat=None;unlocated.lon=None
        invalid = self.article('Bad coordinates',5,self.pa,[self.a1]);invalid.lon=500
        self.article('A previous',10,self.pa,[self.a1])
        for day in (10,11,12,13):self.article(f'B previous {day}',day,self.pb,[self.b1])
        self.article('Wrong stream',1,self.pb,[self.a1])
        self.article('Inactive requirement',1,self.pa,[self.inactive])
        irrelevant = self.article('Irrelevant',1,self.pa,[self.a1]);irrelevant.status='irrelevant'
        self.article('Future',-1,self.pa,[self.a1])
        self.db.commit()

    def test_overview_unique_article_counts_scope_and_trends(self):
        self.data()
        response = self.client.get('/api/overview?window=7d')
        self.assertEqual(response.status_code,200,response.text)
        a,b = response.json()['dashboards']
        self.assertEqual((a['count'],a['previous_count'],a['direction']),(4,1,'rising'))
        self.assertEqual((b['count'],b['previous_count'],b['direction']),(1,4,'falling'))
        self.assertEqual(a['pir_count'],2)
        self.assertEqual(a['geolocated_count'],2)
        self.assertEqual(a['unlocated_count'],2)
        self.assertEqual(sum(a['series']['counts']),4)
        self.assertEqual(len(a['series']['counts']),7)
        # Points are aggregated per place; counts cover every geolocated article.
        self.assertEqual(sum(p['count'] for p in a['points']),2)
        self.assertFalse(a['points_truncated'])
        self.assertEqual(b['points'][0]['reports'][0]['title'],'Shared')
        for window,length in [('30d',30),('90d',90)]:
            dashboard = self.client.get(f'/api/overview?window={window}').json()['dashboards'][0]
            self.assertEqual(len(dashboard['series']['counts']),length)
            self.assertEqual(sum(dashboard['series']['counts']),dashboard['count'])
        day = self.client.get('/api/overview?window=24h')
        self.assertEqual(day.status_code,200,day.text)
        series = day.json()['dashboards'][0]['series']
        self.assertEqual((series['bucket'],len(series['counts'])),('hour',24))
        self.assertEqual(sum(series['counts']),day.json()['dashboards'][0]['count'])
        self.assertEqual(self.client.get('/api/overview?window=12h').status_code,422)

    def test_equal_reporting_volume_is_stable(self):
        for day in (1,2,10,11):self.article(f'Stable {day}',day,self.pa,[self.a1])
        self.db.commit()
        dashboard = self.client.get('/api/overview?window=7d').json()['dashboards'][0]
        self.assertEqual((dashboard['count'],dashboard['previous_count']),(2,2))
        self.assertEqual(dashboard['direction'],'steady')
        self.assertEqual(dashboard['change_pct'],0)

    def test_point_cap_never_caps_counts_and_inactive_pirs_do_not_match(self):
        for n in range(305):self.article(f'Point {n}',1,self.pa,[self.a1])
        self.db.commit()
        a = self.client.get('/api/overview').json()['dashboards'][0]
        self.assertEqual(a['count'],305)
        self.assertEqual(a['geolocated_count'],305)
        # No longer capped at the latest 300: every geolocated article is on the globe,
        # grouped by place with at most 20 sample reports for click-through.
        self.assertEqual(sum(p['count'] for p in a['points']),305)
        self.assertFalse(a['points_truncated'])
        self.assertTrue(all(len(p['reports'])<=20 for p in a['points']))
        self.a1.active=False;self.a2.active=False;self.db.commit()
        a = self.client.get('/api/overview').json()['dashboards'][0]
        self.assertEqual(a['count'],0);self.assertEqual(a['points'],[])

    def test_globe_points_follow_the_selected_period(self):
        self.article('Today',.5,self.pa,[self.a1]);self.article('Recent',3,self.pa,[self.a1]);self.article('Older',20,self.pa,[self.a1]);self.article('Oldest',60,self.pa,[self.a1])
        self.db.commit()
        totals={w:sum(p['count'] for p in self.client.get(f'/api/overview?window={w}').json()['dashboards'][0]['points']) for w in ('24h','7d','30d','90d')}
        self.assertEqual(totals,{'24h':1,'7d':2,'30d':3,'90d':4})

    def summary(self,status='done',content=None):
        summary = Summary(set_id=self.a.id,period_label='Last 7 days',period_start=AT-timedelta(days=7),period_end=AT,
                          status=status,content=content or '## BLUF\nA new development [A1].\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))\n\n![remote](https://evil.example/image.png)',
                          model='claude-test',article_count=1,references={
                              'A1':{'url':'https://example.com/report?q=1&lang=en','title':'Source <unsafe>','date':AT.isoformat(),'source':'Example'},
                              'A2':{'url':'javascript:alert(1)','title':'Unsafe URL'},
                              'A3':{'url':'http://[','title':'Malformed URL'}})
        self.db.add(summary);self.db.commit();return summary

    def test_summary_exports_preserve_sources_metadata_and_safe_html(self):
        summary = self.summary()
        for format,media in [('html','text/html'),('md','text/markdown'),('txt','text/plain'),('json','application/json')]:
            response = self.client.get(f'/api/summaries/{summary.id}/export?format={format}')
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn(media,response.headers['content-type'])
            self.assertIn(f'.{format}"',response.headers['content-disposition'])
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            self.assertIn('claude-test',response.text)
            self.assertIn('2026-04-24',response.text)
            if format=='html':
                self.assertIn('<!doctype html>',response.text)
                self.assertIn('https://example.com/report',response.text)
                self.assertIn('Sources',response.text)
                self.assertNotIn('<script',response.text.lower())
                self.assertNotIn('<img',response.text.lower())
                self.assertNotIn('href="javascript:',response.text.lower())
                self.assertIn('default-src',response.headers['content-security-policy'])
            elif format=='md':
                self.assertIn('[A1]: <https://example.com/report',response.text)
            elif format=='txt':
                self.assertIn('https://example.com/report',response.text)
            else:
                self.assertEqual(response.json()['references']['A1']['title'],'Source <unsafe>')
                self.assertEqual(response.json()['article_count'],1)

    def test_export_readiness_formats_and_filename_safety(self):
        pending = self.summary(status='pending')
        self.assertEqual(self.client.get(f'/api/summaries/{pending.id}/export').status_code,409)
        failed = self.summary(status='failed')
        self.assertEqual(self.client.get(f'/api/summaries/{failed.id}/export?format=md').status_code,409)
        self.assertEqual(self.client.get('/api/summaries/999999/export').status_code,404)
        self.assertEqual(self.client.get(f'/api/summaries/{pending.id}/export?format=exe').status_code,422)
        done = self.summary()
        self.a.name='../../<title><script>\r\nInjected: unsafe';self.db.commit()
        response = self.client.get(f'/api/summaries/{done.id}/export')
        self.assertNotIn('\r',response.headers['content-disposition'])
        self.assertNotIn('\n',response.headers['content-disposition'])
        self.assertNotIn('../',response.headers['content-disposition'])
        self.assertNotIn('<script>',response.text)


if __name__=='__main__':unittest.main()

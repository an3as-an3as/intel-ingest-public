"""Load fictional demo data into an EMPTY installation, for trying the UI or screenshots.

    docker compose exec api python -m app.demo_seed          # preview only
    docker compose exec api python -m app.demo_seed --apply  # write demo data

All dashboards, requirements, streams, articles and the summary are invented.
Article URLs use the reserved `.example` domain. No API calls are made, streams are
saved paused, and the command refuses to run if any dashboards or articles exist.
"""
import argparse
import hashlib
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .models import (AppSetting, Article, ArticlePir, ArticleProfile, Pir, PirSet, ProfileDashboard,
                     SourceProfile, Summary)

DEMO_KEY = 'demo_data'

# (name, description, event_type, [requirements], [(place, lat, lon, country, region, weight)], [title templates])
DASHBOARDS = [
    ('Maritime Security — Baltic & North Sea',
     'Fictional demo: threats to shipping, ports and subsea infrastructure in northern European waters.',
     'maritime',
     [('Subsea infrastructure', 'Which incidents affect undersea cables or pipelines?', 1),
      ('Port disruption', 'Which ports report closures, strikes or security incidents?', 2),
      ('Shadow fleet activity', 'Where are sanctioned or uninsured tankers operating?', 2)],
     [('Gulf of Finland', 59.9, 26.0, 'FI', 'northern_europe', 5), ('Gotland', 57.5, 18.5, 'SE', 'northern_europe', 3),
      ('Gdańsk', 54.35, 18.65, 'PL', 'eastern_europe', 3), ('Rotterdam', 51.92, 4.48, 'NL', 'western_europe', 3),
      ('Kiel Canal', 54.3, 9.9, 'DE', 'western_europe', 2), ('Bornholm', 55.1, 14.9, 'DK', 'northern_europe', 2),
      ('Tallinn', 59.44, 24.75, 'EE', 'northern_europe', 2), ('North Sea platform area', 57.0, 2.5, 'NO', 'northern_europe', 2)],
     ['Cable fault reported near {p}; operator investigates possible anchor drag',
      'Coast guard shadows tanker loitering off {p}',
      'Port authority in {p} briefly halts traffic after security alert',
      'Survey vessel spotted over pipeline route near {p}',
      'Insurers flag uninsured tankers transiting {p}',
      'Navy exercise near {p} focuses on protecting subsea assets']),
    ('Cyber Incidents — Europe',
     'Fictional demo: disruptive cyber attacks against public services and critical infrastructure.',
     'cyber',
     [('Ransomware on public services', 'Which public bodies are hit by ransomware?', 1),
      ('DDoS campaigns', 'Which governments or banks face DDoS attacks?', 2),
      ('Infrastructure intrusions', 'Are energy, water or transport operators breached?', 1)],
     [('Berlin', 52.52, 13.4, 'DE', 'western_europe', 3), ('Paris', 48.86, 2.35, 'FR', 'western_europe', 3),
      ('Warsaw', 52.23, 21.01, 'PL', 'eastern_europe', 3), ('Vilnius', 54.69, 25.28, 'LT', 'northern_europe', 2),
      ('Madrid', 40.42, -3.7, 'ES', 'southern_europe', 2), ('Stockholm', 59.33, 18.07, 'SE', 'northern_europe', 2),
      ('London', 51.51, -0.13, 'GB', 'western_europe', 3), ('Rome', 41.9, 12.5, 'IT', 'southern_europe', 2)],
     ['Ransomware attack disrupts municipal services in {p}',
      'Government websites in {p} hit by DDoS wave',
      'Regional hospital network in {p} reports data breach',
      'Water utility near {p} isolates systems after intrusion attempt',
      'Rail ticketing outage in {p} blamed on cyber attack',
      'Banks in {p} report short service disruption after DDoS']),
    ('Civil Unrest — Global',
     'Fictional demo: large protests, strikes and unrest affecting travel and business continuity.',
     'civil_unrest',
     [('Mass protests', 'Where do protests exceed 10,000 participants?', 2),
      ('Violent clashes', 'Where do protests turn violent or face crackdowns?', 1),
      ('Transport strikes', 'Which strikes disrupt airports, ports or rail?', 2)],
     [('Nairobi', -1.29, 36.82, 'KE', 'sub_saharan_africa', 2), ('Santiago', -33.45, -70.67, 'CL', 'latin_america', 2),
      ('Jakarta', -6.2, 106.85, 'ID', 'southeast_asia', 2), ('Lima', -12.05, -77.04, 'PE', 'latin_america', 2),
      ('Dhaka', 23.81, 90.41, 'BD', 'south_asia', 2), ('Lagos', 6.52, 3.38, 'NG', 'sub_saharan_africa', 2),
      ('Buenos Aires', -34.6, -58.38, 'AR', 'latin_america', 2), ('Manila', 14.6, 120.98, 'PH', 'southeast_asia', 1),
      ('Paris', 48.86, 2.35, 'FR', 'western_europe', 2), ('Mexico City', 19.43, -99.13, 'MX', 'latin_america', 2)],
     ['Tens of thousands march in {p} over cost of living',
      'Police use tear gas as protest in {p} turns violent',
      'Nationwide transport strike paralyses {p}',
      'Airport workers in {p} announce 48-hour walkout',
      'Curfew imposed in parts of {p} after clashes',
      'Students rally in {p} against tuition increases']),
]
OUTLETS = ['northwire.example', 'harbourdaily.example', 'eurodesk.example', 'globalbrief.example',
           'citypost.example', 'signalnews.example']


def _counts(db):
    return db.scalar(select(func.count()).select_from(PirSet)), db.scalar(select(func.count()).select_from(Article))


def seed(db, now=None, rng=None):
    now = now or datetime.now(timezone.utc)
    rng = rng or random.Random(42)
    created = {'dashboards': 0, 'articles': 0}
    article_index = 0
    summary_target = None
    for name, description, event_type, requirements, places, templates in DASHBOARDS:
        dashboard = PirSet(name=name, description=description)
        db.add(dashboard); db.flush(); created['dashboards'] += 1
        pirs = []
        for i, (title, question, priority) in enumerate(requirements, 1):
            pir = Pir(set_id=dashboard.id, code=f'D{dashboard.id}-{i}', title=title, question=question,
                      indicators='Fictional demo requirement.', priority=priority)
            db.add(pir); pirs.append(pir)
        stream = SourceProfile(name=f'{name} (demo stream)', source='newscatcher', enabled=False,
                               interval_minutes=180, params={'event_presets': [event_type], 'demo': True})
        db.add(stream); db.flush()
        db.add(ProfileDashboard(profile_id=stream.id, set_id=dashboard.id))
        weighted = [p for p in places for _ in range(p[5])]
        recent = []
        for n in range(110):
            # Skew towards recent days so week/month/quarter views differ visibly.
            age = timedelta(hours=min(89 * 24, rng.expovariate(1 / 240)))
            place, lat, lon, country, region, _ = rng.choice(weighted)
            title = rng.choice(templates).format(p=place)
            article_index += 1
            digest = hashlib.sha256(f'demo-{article_index}'.encode()).hexdigest()
            article = Article(url=f'https://{rng.choice(OUTLETS)}/demo/{article_index}', title=title,
                              title_hash=digest, description=f'Fictional demo report: {title.lower()}.',
                              source_domain=rng.choice(OUTLETS), source_country=country, language='en',
                              published_at=now - age, ingested_at=now - age, profile_id=stream.id,
                              status='enriched', ai_summary=f'Fictional demo: {title}.', event_type=event_type,
                              region=region, countries=[country], location_name=place,
                              lat=lat + rng.uniform(-.35, .35), lon=lon + rng.uniform(-.35, .35),
                              geo_precision='city', enriched_at=now - age, model='demo-data')
            db.add(article); db.flush(); created['articles'] += 1
            db.add(ArticleProfile(article_id=article.id, profile_id=stream.id))
            for pir in rng.sample(pirs, k=rng.choice([1, 1, 2])):
                db.add(ArticlePir(article_id=article.id, pir_id=pir.id, score=round(rng.uniform(.55, .95), 2),
                                  rationale='Fictional demo match.'))
            if age < timedelta(days=7):
                recent.append(article)
        if summary_target is None:
            summary_target = (dashboard, recent[:6])
    dashboard, cited = summary_target
    refs = {f'A{a.id}': {'title': a.title, 'url': a.url, 'date': a.published_at.isoformat(), 'source': a.source_domain}
            for a in cited}
    ids = list(refs)
    content = (f'## Bottom line\nSubsea infrastructure around the Gulf of Finland **likely** remains the main concern '
               f'this week, with repeated reports of vessels loitering over cable routes [{ids[0]}][{ids[1]}].\n\n'
               f'## Key judgements\n- Port operations were briefly disrupted by security alerts [{ids[2]}].\n'
               f'- Shadow-fleet tanker activity continues to draw coast-guard attention [{ids[3]}].\n'
               f'- No confirmed sabotage was reported; investigations are ongoing [{ids[4]}].\n\n'
               f'## Outlook\nExpect continued naval patrols and insurer scrutiny over the next two weeks (moderate confidence).\n\n'
               f'*This is fictional demo content.*')
    db.add(Summary(set_id=dashboard.id, period_label='Last 7 days', period_start=now - timedelta(days=7),
                   period_end=now, status='done', content=content, article_count=len(cited), references=refs,
                   model='demo-data'))
    db.add(AppSetting(key=DEMO_KEY, value={'seeded_at': now.isoformat(), **created}))
    db.commit()
    return created


def main():
    from .db import init_db, session_scope
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='write demo data (default: preview only)')
    args = parser.parse_args()
    init_db()
    with session_scope() as db:
        dashboards, articles = _counts(db)
        if dashboards or articles:
            raise SystemExit('Refusing to load demo data: this installation already has dashboards or articles.')
        if not args.apply:
            print(f'Would create {len(DASHBOARDS)} fictional dashboards, paused demo streams, '
                  f'{110 * len(DASHBOARDS)} fictional articles and one summary. Re-run with --apply.')
            return
        print('Created', seed(db))


if __name__ == '__main__':
    main()

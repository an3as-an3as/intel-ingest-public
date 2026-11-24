#!/usr/bin/env python3
"""Export private pilot candidates for manual review. No APIs, scripts or external assets.

python3 scripts/export_pilot_review.py --pilot PILOT_ID
Existing review files are never overwritten: the CSV may contain human annotations.
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def escape(value):
    return html.escape(str(value or ''), quote=True)


def safe_url(value):
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password else None
    except (ValueError, TypeError):
        return None


def csv_cell(value):
    value = str(value or '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def render(articles, variants, lanes, baseline):
    urls = set(articles)
    groups = [('additional', 'Additional to the baseline', sorted(urls - baseline)),
              ('baseline', 'Found by the baseline', sorted(urls & baseline))]
    intro = ''.join(f'<a href="#{key}">{escape(title)} ({len(items)})</a> ' for key, title, items in groups)
    content = []
    for key, title, items in groups:
        counts = Counter(articles[u].get('language', 'unknown') for u in items)
        content.append(f'<section id="{key}"><h2>{escape(title)} — {len(items)} URLs</h2>'
                       f'<p>{escape(", ".join(f"{lang}: {count}" for lang, count in sorted(counts.items())))}</p>')
        for url in sorted(items, key=lambda u: (articles[u].get('language',''), articles[u].get('title','').casefold(), u)):
            article = articles[url]
            row_id = 'a-' + hashlib.sha256(url.encode()).hexdigest()[:12]
            link = safe_url(url)
            title_html = escape(article.get('title') or url)
            if link:
                title_html = f'<a href="{escape(link)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{title_html}</a>'
            content.append(f'<article id="{row_id}"><h3>{title_html}</h3>'
                f'<p class="meta">{escape(article.get("language","unknown"))} · {escape(article.get("publisher"))}'
                f' · {escape(article.get("published_at") or "Publication time unavailable")} · Review ID {row_id}</p>'
                f'<p class="meta">Found by: {escape(", ".join(sorted(variants.get(url,[]))))}'
                f' · Query lanes: {escape(", ".join(sorted(lanes.get(url,[]))))}</p>'
                f'<details><summary>Returned excerpt (not independently verified)</summary><p>{escape(article.get("description","")[:600]) or "No excerpt returned."}</p></details>'
                '</article>')
        content.append('</section>')
    document = '<!doctype html><html lang="en"><head><meta charset="utf-8">' \
        '<meta name="viewport" content="width=device-width, initial-scale=1">' \
        '<meta name="referrer" content="no-referrer">' \
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' \
        '<title>Private pilot article review</title><style>' \
        'body{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 20px;color:#171717;background:#fafafa}' \
        'nav{display:flex;gap:16px;flex-wrap:wrap}h1{font-size:26px}h2{margin-top:36px}h3{font-size:18px;margin:0}' \
        'article{padding:18px;margin:12px 0;background:white;border:1px solid #ddd;border-radius:8px;overflow-wrap:anywhere}' \
        'a{color:#1456a0}.meta{font-size:13px;color:#555}summary{cursor:pointer}details p{white-space:pre-wrap}' \
        '</style></head><body><h1>Private pilot article review</h1>' \
        f'<p>{len(articles)} unique URL candidates. These are <strong>not classified or validated cybersecurity reports</strong>.</p>' \
        '<p>Start with the additional multilingual results. Use your browser’s Find (Cmd+F) to search titles.' \
        ' Click a title to open its publisher; some sources may have paywalls. Excerpts are limited to returned metadata.</p>' \
        '<p>For annotations, open <a href="articles-review.csv" download>the review CSV</a> in a spreadsheet. ' \
        'Fill review_label with relevant / partly_relevant / irrelevant / uncertain and add reviewer_notes. ' \
        'The HTML itself does not save annotations. Keep both files private.</p>' \
        '<p>No API calls, external images, scripts, fonts or classification run when opening this page. ' \
        'Only clicking source links loads external sites. URL overlap is not proof of independent sources or unique real-world events.</p>' \
        f'<nav>{intro}</nav>' + ''.join(content) + '</body></html>'
    fields = ['review_id','cohort','language','title','publisher','published_at','url','found_by','query_lanes','returned_excerpt','review_label','reviewer_notes']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields);writer.writeheader()
    for key, _, items in groups:
        for url in items:
            a = articles[url]
            row = {'review_id':'a-'+hashlib.sha256(url.encode()).hexdigest()[:12], 'cohort':key,
                   **{field:a.get(field,'') for field in ('language','title','publisher','published_at')},
                   'url':url, 'found_by':', '.join(sorted(variants.get(url,[]))), 'query_lanes':', '.join(sorted(lanes.get(url,[]))),
                   'returned_excerpt':a.get('description','')[:600], 'review_label':'', 'reviewer_notes':''}
            writer.writerow({k:csv_cell(v) for k,v in row.items()})
    return document, output.getvalue()


def export(pilot_id):
    if not re.fullmatch(r'[a-f0-9]{32}',pilot_id):
        raise ValueError('Invalid pilot ID')
    directory = ROOT / 'data/pilots' / pilot_id
    path = directory / 'pilot.sqlite'
    for parent in (path,*path.parents):
        if parent.is_symlink():
            raise ValueError('Symlinked pilot paths are forbidden')
        if parent == ROOT:break
    destinations = [directory/'articles-review.html',directory/'articles-review.csv']
    if any(os.path.lexists(p) for p in destinations):
        raise ValueError('Review files already exist; refusing to overwrite possible human annotations')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        plan=json.loads(db.execute('SELECT value FROM pilot_meta WHERE key="plan"').fetchone()[0])
        baseline_name=plan['variants'][0]['name']
        articles={r['url']:json.loads(r['article_json']) for r in db.execute('SELECT * FROM pilot_articles')}
        variants,lanes,baseline={},{},set()
        for r in db.execute('SELECT m.url,a.variant,a.request_json FROM pilot_memberships m JOIN pilot_attempts a ON a.id=m.attempt_id'):
            variants.setdefault(r['url'],set()).add(r['variant'])
            lanes.setdefault(r['url'],set()).add(json.loads(r['request_json']).get('language_lane','original'))
            if r['variant']==baseline_name:baseline.add(r['url'])
    documents=render(articles,variants,lanes,baseline)
    for destination, document in zip(destinations,documents):
        fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',newline='',encoding='utf-8') as stream:stream.write(document)
    return destinations


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot',required=True)
    args=parser.parse_args()
    subprocess.run([str(ROOT/'scripts/development.sh'),'check'],cwd=ROOT,check=True)
    try:
        paths=export(args.pilot)
    except (ValueError,OSError,sqlite3.Error):
        print('Export refused: invalid/missing pilot or review files already exist. Existing files were not overwritten.')
        return 1
    for path in paths:print(path)
    return 0


if __name__=='__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare human keyword-review fixtures from an EXISTING private pilot, offline.

No provider/LLM calls or saved-stream edits. The only HTTP is localhost:8081 metadata,
profile reads and the local compiler preview. Existing review files are preserved.
"""
import argparse
from collections import Counter, defaultdict
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
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://127.0.0.1:8081'


def literal_terms(article, terms):
    # Literal metadata screening, NOT provider term attribution or full-text matching.
    text = (article.get('title','')+' '+article.get('description','')).casefold()
    return [term for term in terms if term.casefold() in text]


def select_sample(articles, terms, baseline_urls, size, seed):
    hits = {u for u,a in articles.items() if literal_terms(a,terms)}
    if not len(hits) <= size <= len(articles):
        raise ValueError('Sample size must retain every literal hit and not exceed available URLs')
    groups = defaultdict(list)
    for url in set(articles)-hits:
        groups[(articles[url].get('language','unknown'),'original-language-pilot' if url in baseline_urls else 'multilingual-additional')].append(url)
    if size-len(hits)<len(groups):
        raise ValueError('Sample must include at least one control from each language/cohort stratum')
    for urls in groups.values():
        urls.sort(key=lambda url: hashlib.sha256((seed+'\n'+url).encode()).hexdigest())
    chosen = set(hits); positions=Counter()
    while len(chosen)<size:
        for group in sorted(groups):
            if positions[group]<len(groups[group]) and len(chosen)<size:
                chosen.add(groups[group][positions[group]]);positions[group]+=1
    strata=[{'language':g[0],'pilot_cohort':g[1],'available_controls':len(groups[g]),'sampled_controls':positions[g],
             'control_population_weight':len(groups[g])/positions[g] if positions[g] else None} for g in sorted(groups)]
    return chosen,hits,strata


def safe_cell(value):
    value=str(value or '')
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value


def write_private(path,text):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:stream.write(text)


def local_json(path, body=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,
                                  headers={'Content-Type':'application/json'},method='POST' if body is not None else 'GET')
    with opener.open(request,timeout=15) as response:return json.load(response)


def prepare(pilot_id,profile_id,category,size):
    if not re.fullmatch(r'[a-f0-9]{32}',pilot_id) or category!='cyber':
        raise ValueError('Invalid pilot/category')
    pilot=ROOT/'data/pilots'/pilot_id
    for parent in (pilot,*pilot.parents):
        if parent.is_symlink():raise ValueError('Symlinked pilot paths are forbidden')
        if parent==ROOT:break
    vocab=json.loads((ROOT/'backend/app/sources/event_vocabularies.json').read_text())
    terms=vocab['legacy-v1']['events'][category]['core']
    with closing(sqlite3.connect((pilot/'pilot.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        plan=json.loads(db.execute('SELECT value FROM pilot_meta WHERE key="plan"').fetchone()[0])
        first_variant=plan['variants'][0]['name']
        articles={r['url']:json.loads(r['article_json']) for r in db.execute('SELECT * FROM pilot_articles')}
        baseline_urls={r['url'] for r in db.execute('SELECT m.url FROM pilot_memberships m JOIN pilot_attempts a ON a.id=m.attempt_id WHERE a.variant=?',(first_variant,))}
    selected,hits,strata=select_sample(articles,terms,baseline_urls,size,pilot_id+'-'+category+'-legacy-review-v1')
    meta=local_json('/api/meta')
    if meta['environment']!='development' or meta['newscatcher_configured'] or meta['claude_configured']:
        raise ValueError('Expected offline development environment')
    profile=next(p for p in local_json('/api/profiles') if p['id']==profile_id)
    if profile['enabled'] or profile['source']!='newscatcher' or profile['params'].get('endpoint','search')!='search':
        raise ValueError('Select a paused NewsCatcher Search stream')
    if not 1<=profile['params'].get('max_records',100)<=50:
        raise ValueError('Use the verified account article cap (50 or fewer)')
    # PROPOSED baseline only: do not save, activate, edit vocabularies or approve translations.
    params={**profile['params'],'keywords':[],'query':'','event_presets':[category],
            'event_vocabulary_version':'legacy-v1','event_vocabulary_tiers':['core'],'multilingual_enabled':False,
            'max_requests_per_poll':1,'max_credits_per_poll':1}
    params.pop('translation_review_id',None)
    payload={**{k:profile[k] for k in ('name','source','interval_minutes','dashboard_ids')},'enabled':False,'params':params}
    preview=local_json('/api/profiles/preview-query',payload)
    if preview['request_count']!=1 or preview['estimated_credits_per_poll']!=1:
        raise ValueError('Expected one bounded low-effort baseline request')
    after=next(p for p in local_json('/api/profiles') if p['id']==profile_id)
    if after!=profile:raise ValueError('Stream changed concurrently; review the settings before continuing')
    folder=pilot/(category+'-keyword-review')
    folder.mkdir(mode=0o700,exist_ok=False)  # Never overwrite human annotations.
    instructions='''# Cyber keyword review — human labels first

This package uses existing Expanded-vocabulary pilot results, NOT a newly collected
Legacy-only corpus. The local proposed Legacy query has NOT been sent to NewsCatcher.
No provider/model calls, stream saves, translation approvals or vocabulary edits occur.

## Start here

1. Open review-sample.html for reading and review-sample.csv as your master label file.
2. The first group contains literal Legacy phrases in returned title/excerpt metadata;
   the rest are comparison controls. legacy-metadata-review.* is an optional subset,
   NOT additional articles to label twice. Use review_id/URL to merge any prior labels.
   HTML is a reading companion, not an annotation form. Keep annotations in CSV.
3. Return the labelled master CSV for analysis. Do not change keyword versions yet.

Labels:
- cyber_relevance: direct / context / irrelevant / uncertain.
  direct = specific malicious cyber activity, incident/compromise, or a concrete
  vulnerability/exposure with operational cybersecurity implications.
  context = substantive threat intelligence, response or policy useful to answering
  cyber questions, without a directly reported incident. General AI/business/sports/
  politics with only a security mention is not automatically cyber-relevant.
- geography_relevance: dk_no_se_related / outside / unclear.
  Label this independently: a real cyber report outside scope is NOT evidence that
  its cyber keyword is bad. Use actors/assets/events, not publisher country alone.
- reason_code: topic_mismatch / passing_mention / wrong_geography / insufficient_info /
  substantive_cyber / other (or your own short reason).
- evidence_basis: headline_excerpt / original_article / insufficient_access.
- reviewer_notes: one short supporting reason, especially borderline cases.

Open original sources if the metadata is insufficient. Mark uncertain when access
or evidence is insufficient, rather than treating a paywall or missing excerpt as
irrelevant. Syndication/URL duplicates are separate from topic relevance; a valuable
single-source report must not be discarded merely for lacking corroboration.

## Analysis safeguards

The first group is a metadata literal screen only. Missing a literal phrase in an
excerpt does not mean it is absent from the full article, and a phrase appearing
is NOT proof that it caused retrieval. Returned descriptions can be provider English
summaries of local-language articles; a hit in that summary is not an original-text
match. Search semantics/ranking require live checks.
All literal hits were retained; other reports were sampled deterministically across
language/pilot-cohort strata. This is deliberately enriched, not a simple random
precision sample. Use the supplied stratum counts for any weighted analysis; those
weights cover only the already-returned capped pilot corpus, not all news.

Do not prune terms based on overall unweighted labels alone. Analyse geography and
language separately, identify positive examples a narrower query would lose, then
freeze a candidate and test on fresh/held-out reports before accepting it. No known
reference set currently establishes recall. The remaining corpus is untouched by
this review selection but has not been hidden by an access-control mechanism.

The old pilot's 'baseline' was original-language Expanded vocabulary, NOT frozen
Legacy. The proposed true Legacy query removes the objective sentence from literal
keywords, uses only the category's frozen core phrases and disables multilingual
expansion for the reference test. Other filters/geography/languages are retained.
It is one proposed query, not yet a paid run or a fair paired experiment. Translation
comparisons/new vocabularies require their own review and bounded approval later.
Never edit legacy-v1 in place: propose an explicit new experimental version instead.
'''
    manifest={'category':category,'vocabulary':'legacy-v1','terms':terms,'source_pilot':pilot_id,
        'source_corpus':'existing Expanded-vocabulary pilot, not fresh Legacy retrieval',
        'source_url_count':len(articles),'sample_size':len(selected),'literal_metadata_hits':len(hits),
        'sampled_nonliteral_controls':len(selected-hits),'unselected_urls':len(articles)-len(selected),
        'literal_hit_population_weight':1,'prior_annotations_overwritten':False,
        'selected_language_counts':dict(Counter(articles[u].get('language','unknown') for u in selected)),
        'control_strata':strata,'sampling_seed':pilot_id+'-'+category+'-legacy-review-v1',
        'paid_requests_made':0,'model_calls_made':0,'saved_stream_changed':False,
        'proposal_changes':{'configured_custom_keywords_removed':profile['params'].get('keywords',[]),
                            'configured_advanced_query_removed':profile['params'].get('query',''),
                            'event_category':category,'vocabulary':'legacy-v1/core',
                            'multilingual_expansion':'off for proposed baseline'},
        'original_article_language_filter':profile['params'].get('languages',[]),
        'original_coverage_countries':profile['params'].get('coverage_countries',[]),
        'proposed_baseline_requests':preview['request_count'],'proposed_nominal_credits':preview['estimated_credits_per_poll']}
    write_private(folder/'README.md',instructions)
    write_private(folder/'manifest.json',json.dumps(manifest,indent=2,ensure_ascii=False))
    write_private(folder/'legacy-baseline-preview.json',json.dumps({'status':'offline_proposal_not_executed','preview':preview},indent=2,ensure_ascii=False))
    fields=['review_id','sample_group','language','pilot_cohort','legacy_terms_in_metadata','title','publisher','url','returned_excerpt',
            'cyber_relevance','geography_relevance','reason_code','evidence_basis','reviewer_notes']
    def make_files(stem,urls):
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
        cards=[]
        for url in sorted(urls,key=lambda u:(u not in hits,articles[u].get('language',''),hashlib.sha256(u.encode()).hexdigest())):
            a=articles[url];rid='a-'+hashlib.sha256(url.encode()).hexdigest()[:12]
            row={'review_id':rid,'sample_group':'legacy_literal_metadata' if url in hits else 'nonliteral_metadata_control',
                 'language':a.get('language','unknown'),'pilot_cohort':'original-language-pilot' if url in baseline_urls else 'multilingual-additional',
                 'legacy_terms_in_metadata':', '.join(literal_terms(a,terms)),
                 'title':a.get('title',''),'publisher':a.get('publisher',''),'url':url,'returned_excerpt':a.get('description','')[:6000],
                 'cyber_relevance':'','geography_relevance':'','reason_code':'','evidence_basis':'','reviewer_notes':''}
            writer.writerow({k:safe_cell(v) for k,v in row.items()})
            e=lambda value:html.escape(str(value),quote=True)
            # URLs originated in the pilot's HTTP(S)-only URL validation; guard again for export.
            href=url if url.startswith(('https://','http://')) else '#'
            cards.append(f'<article><h2><a href="{e(href)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{e(row["title"])}</a></h2>'
                f'<p>{e(rid)} · {e(row["language"])} · {e(row["pilot_cohort"])} · {e(row["sample_group"])}</p>'
                f'<p>Literal phrases in returned metadata: {e(row["legacy_terms_in_metadata"] or "None observed — not a full-text check")}</p>'
                f'<details><summary>Returned excerpt — unverified</summary><p>{e(row["returned_excerpt"])}</p></details></article>')
        page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Cyber keyword relevance review</title><style>body{font:16px/1.5 system-ui;max-width:960px;margin:24px auto;padding:0 16px;background:#fafafa}article{background:white;border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0;overflow-wrap:anywhere}h2{font-size:18px}a{color:#1456a0}summary{cursor:pointer}</style></head><body>
<h1>Cyber keyword relevance review</h1><p>Existing Expanded-search candidates, not a fresh Legacy search. No labels have been assigned. English term hits may occur in provider-translated summaries, not original text.</p>
<p>Label cybersecurity relevance and geography separately. Read the <a href="README.md">review instructions</a>. HTML does not save labels.</p>'''
        page+=f'<p><a href="{stem}.csv" download>Open this set as an annotation CSV</a> · {len(urls)} candidates.</p>'
        page+=''.join(cards)+'</body></html>'
        write_private(folder/(stem+'.csv'),buffer.getvalue());write_private(folder/(stem+'.html'),page)
    make_files('legacy-metadata-review',hits)
    make_files('review-sample',selected)
    return folder,manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot',required=True);parser.add_argument('--profile-id',type=int,required=True)
    parser.add_argument('--category',choices=['cyber'],default='cyber');parser.add_argument('--sample-size',type=int,default=100)
    args=parser.parse_args()
    subprocess.run([str(ROOT/'scripts/development.sh'),'check'],cwd=ROOT,check=True)
    try:
        folder,manifest=prepare(args.pilot,args.profile_id,args.category,args.sample_size)
    except (ValueError,KeyError,StopIteration,OSError,sqlite3.Error):
        print('Preparation refused: review existing files, category, sample size or offline stream settings. Nothing was saved to the app.')
        return 1
    print(json.dumps({'review_folder':str(folder),**manifest},indent=2,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())

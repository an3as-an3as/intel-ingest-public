#!/usr/bin/env python3
"""Manual isolated pilot CLI. No web stack/worker/provider settings are modified.

Run with the project's Python test environment. Every command validates the pinned
DEVELOPMENT stack's isolation; live credentials/approval are separate and default off.
See docs/live-pilot.md. No command below is an authorisation to make paid calls.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))


def path_for(pilot_id):
    if not re.fullmatch(r'[a-f0-9]{32}', pilot_id):
        raise ValueError('Pilot ID must be the generated 32-character ID')
    path = ROOT / 'data' / 'pilots' / pilot_id / 'pilot.sqlite'
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Symlinked pilot paths are forbidden')
        if parent == ROOT:
            break
    return path


def example():
    def variant(name, query):
        return {'name':name,'requests':[{'endpoint':'search','language_lane':'original',
            'parameters':{'q':query,'effort':'low','limit':10,'search_window':'60m','sort_by':'published_at','content_type':'news'}}]}
    return {'mode':'simulation','name':'Offline comparison template',
        'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
        'allowed_endpoints':['search'],'access_reference':'Replace with separately checked test-plan access note; never a key',
        'access_confirmed':False,
        'limits':{'max_http_requests':6,'max_collection_requests':2,'max_nominal_credits':2,
                  'max_model_calls':4,'max_reserved_model_tokens':8000},
        'variants':[variant('baseline','Baltic Sea'),variant('experimental','"Baltic Sea" OR Østersøen')],
        'reference_urls':[],'polling_interval_minutes':60,'classification':None,
        'projected_new_unique_per_poll':None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('example',help='Print a simulation-only template; does not create records')
    init = sub.add_parser('init'); init.add_argument('--config',required=True)
    imp = sub.add_parser('import-preview'); imp.add_argument('--name',required=True); imp.add_argument('--file',required=True)
    for name in ('report','show-plan','stop','arm','collect','classify-one'):
        p=sub.add_parser(name);p.add_argument('--pilot',required=True)
        if name in ('arm','collect','classify-one'):p.add_argument('--ack-paid',action='store_true')
        if name=='arm':p.add_argument('--approval-hash',required=True)
        if name=='collect':p.add_argument('--variant',required=True)
        if name in ('collect','classify-one'):
            p.add_argument('--fixtures',help='JSON array of responses; permitted only in simulation ledgers')
    args=parser.parse_args()
    subprocess.run([str(ROOT/'scripts/development.sh'),'check'],cwd=ROOT,check=True,stdout=sys.stderr)
    from app.pilot import Ledger, Refused, import_preview
    from pydantic import ValidationError
    try:
        if args.command=='example':
            result=example()
        elif args.command=='import-preview':
            result=import_preview(args.name,json.loads(Path(args.file).read_text()))
        elif args.command=='init':
            pilot_id=uuid.uuid4().hex
            ledger=Ledger.create(path_for(pilot_id),json.loads(Path(args.config).read_text()))
            result={'pilot_id':pilot_id,'plan_hash':ledger.plan_hash,'mode':ledger.plan.mode,
                    'armed':False,'note':'No requests made. Live execution requires separate approval, test keys and deployment flag.'}
        else:
            ledger=Ledger(path_for(args.pilot))
            fixture=None
            if getattr(args,'fixtures',None):
                responses=json.loads(Path(args.fixtures).read_text())
                if not isinstance(responses,list) or any(not isinstance(r,dict) for r in responses):
                    raise Refused('Fixture file must be an array of response objects')
                responses=iter(responses)
                fixture=lambda kind,spec:next(responses)
            if args.command=='report':result=ledger.report()
            elif args.command=='show-plan':result={'plan_hash':ledger.plan_hash,'plan':ledger.plan.model_dump(mode='json')}
            elif args.command=='stop':ledger.stop();result={'stopped':True,'note':'In-flight requests cannot be cancelled; no subsequent dispatch is allowed.'}
            elif args.command=='arm':ledger.arm(args.approval_hash,args.ack_paid);result={'armed':True,'plan_hash':ledger.plan_hash}
            elif args.command=='collect':
                ledger.collect(args.variant,ack=args.ack_paid,fixture=fixture);result=ledger.report()
            else:
                done=ledger.classify_one(ack=args.ack_paid,fixture=fixture)
                result={'classified_one':done,'report':ledger.report()}
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    except ValidationError as error:
        # Never echo full potentially private config, query text or supplied input values.
        print('Invalid pilot configuration: '+', '.join('.'.join(map(str,e['loc']))+' ('+e['type']+')' for e in error.errors()),file=sys.stderr)
    except Refused as error:
        print(str(error),file=sys.stderr)
    except (OSError,ValueError,KeyError,TypeError,StopIteration,sqlite3.Error):
        print('Pilot command failed: invalid/missing private file, ledger or fixture. No automatic retry.',file=sys.stderr)
    return 1


if __name__=='__main__':
    raise SystemExit(main())

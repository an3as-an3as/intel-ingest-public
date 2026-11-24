#!/usr/bin/env python3
"""Read-only table counts/digests for private upgrade rehearsals; never prints rows.

Run only against an explicitly selected database. Does not initialize schema.
Keep reports private: they reveal aggregate application activity.
"""
import hashlib
import json

from sqlalchemy import MetaData, Table, inspect, select, text

from app.db import engine

EXISTING = ('app_settings', 'article_pirs', 'article_profiles', 'articles', 'pir_sets',
            'pirs', 'profile_dashboards', 'source_profiles', 'summaries', 'worker_states')


def snapshot():
    result = {}
    with engine.connect() as conn:
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        available = set(inspect(conn).get_table_names())
        for name in EXISTING:
            if name not in available:
                raise RuntimeError(f'Missing baseline table: {name}')
            table = Table(name, MetaData(), autoload_with=conn)
            digest, count = hashlib.sha256(), 0
            for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings():
                digest.update(json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=True).encode())
                digest.update(b'\n')
                count += 1
            result[name] = {'count': count, 'sha256': digest.hexdigest()}
        return result


if __name__ == '__main__':
    print(json.dumps(snapshot(), sort_keys=True, indent=2))

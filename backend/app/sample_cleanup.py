"""One-time removal of unchanged legacy samples; never creates application data.

Run `python -m app.sample_cleanup` to preview or add `--apply` to remove them.
Edited templates and articles belonging to any user stream are preserved.
"""

import argparse
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .models import Article, ArticleProfile, PirSet, SourceProfile
from .pipeline.scope import profile_scope

SETS = [
    {
        "name": "Baltic Sea & Nordic Security",
        "description": "Military, hybrid and influence threats to the Nordic-Baltic region.",
        "pirs": [
            ("BAL-1", 1, "Russian military posture near Nordic-Baltic borders",
             "What changes in Russian military activity, deployments or exercises near the Nordic and Baltic states, including Kaliningrad and the Baltic Sea, indicate increased intent or capability to threaten the region?",
             "Troop or equipment movements, snap exercises, airspace or territorial-water violations, naval deployments, GPS jamming, Kaliningrad activity, border incidents."),
            ("BAL-2", 1, "Sabotage of critical undersea and energy infrastructure",
             "Are there incidents or indicators of sabotage, surveillance or reconnaissance against undersea cables, pipelines, offshore energy or ports in the Baltic and North Sea?",
             "Cable or pipeline damage, anchor-drag incidents, suspicious vessels loitering over infrastructure, shadow-fleet vessels, arrests, investigations."),
            ("BAL-3", 2, "Hybrid and influence operations against Nordic-Baltic states",
             "What hybrid activity (disinformation, instrumentalised migration, cyber, arson or sabotage on land) targets Nordic and Baltic states?",
             "Attributed disinformation campaigns, migrants pushed across borders, arson or sabotage arrests, espionage cases, DDoS against government sites."),
        ],
    },
    {
        "name": "Red Sea & Maritime Chokepoints",
        "description": "Threats to commercial shipping through the Red Sea, Bab el-Mandeb and Suez.",
        "pirs": [
            ("RSM-1", 1, "Attacks on commercial shipping",
             "Where, how often and with what means are commercial vessels being attacked or harassed in the Red Sea, Gulf of Aden and Bab el-Mandeb?",
             "Missile, drone or USV attacks; boarding or hijacking; vessel damage or casualties; Houthi claims; UKMTO and MARAD advisories."),
            ("RSM-2", 2, "Shipping diversion and economic impact",
             "How are shipping companies, insurers and Suez Canal traffic responding to the threat?",
             "Route diversions around the Cape, war-risk insurance premiums, Suez Canal transit and revenue figures, carrier announcements."),
            ("RSM-3", 2, "Naval and coalition posture",
             "What naval deployments, coalition operations or strikes affect the maritime security situation?",
             "Warship deployments, escort missions, coalition strikes on launch sites, interceptions."),
        ],
    },
    {
        "name": "Cyber Threats to Critical Infrastructure",
        "description": "State-linked and criminal cyber activity against critical sectors in Europe and North America.",
        "pirs": [
            ("CYB-1", 1, "Disruptive attacks on critical infrastructure",
             "Which cyber attacks have disrupted, or attempted to disrupt, energy, water, transport, health or telecom operators, and who is assessed to be responsible?",
             "Ransomware outages at operators, OT/ICS intrusions, government attributions, CERT advisories, wiper malware."),
            ("CYB-2", 2, "Exploited vulnerabilities in widely used edge and OT products",
             "Which vulnerabilities in widely deployed edge devices or OT products are being actively exploited?",
             "Zero-days, KEV additions, mass-exploitation campaigns, emergency patches."),
        ],
    },
]

PROFILES = [
    ("Nordic-Baltic security (GDELT)", "gdelt", {
        "keywords": ["Baltic Sea", "Kaliningrad", "undersea cable", "Gotland", "Suwalki", "shadow fleet", "Finland border"],
        "languages": ["english"], "lookback_hours": 48, "max_records": 250}),
    ("Red Sea shipping (GDELT)", "gdelt", {
        "keywords": ["Red Sea", "Houthi", "Bab el-Mandeb", "Gulf of Aden", "Suez Canal", "UKMTO"],
        "languages": ["english"], "lookback_hours": 48, "max_records": 250}),
    ("Critical-infrastructure cyber (GDELT)", "gdelt", {
        "keywords": ["ransomware", "cyberattack", "hackers", "zero-day"], "themes": ["CYBER_ATTACK"],
        "combine": "or", "languages": ["english"], "lookback_hours": 48, "max_records": 250}),
]


def remove_samples(s: Session, *, apply: bool = False) -> dict:
    profiles = [p for p in s.scalars(select(SourceProfile))
                if any(p.name == name and p.source == source and p.params == params
                       for name, source, params in PROFILES)]
    dashboards = []
    for dashboard in s.scalars(select(PirSet).options(selectinload(PirSet.pirs))):
        actual = sorted((p.code, p.priority, p.title, p.question, p.indicators) for p in dashboard.pirs)
        if all(p.active for p in dashboard.pirs) and any(
            dashboard.name == sample['name'] and dashboard.description == sample['description']
            and actual == sorted(sample['pirs']) for sample in SETS
        ):
            dashboards.append(dashboard)
    ids = [p.id for p in profiles]
    # A URL fetched by both a sample and a user stream must remain available to the user.
    user_membership = select(ArticleProfile.article_id).where(
        ArticleProfile.article_id == Article.id, ArticleProfile.profile_id.not_in(ids)).exists()
    exclusive_articles = list(s.scalars(select(Article.id).where(
        profile_scope(ids), ~user_membership,
        (Article.profile_id.is_(None) | Article.profile_id.in_(ids)),
    ))) if ids else []
    result = {'applied': apply, 'profiles': [p.name for p in profiles],
              'dashboards': [p.name for p in dashboards], 'exclusive_sample_articles': len(exclusive_articles)}
    if apply:
        if exclusive_articles:
            s.execute(delete(Article).where(Article.id.in_(exclusive_articles)))
        if ids:
            s.execute(delete(SourceProfile).where(SourceProfile.id.in_(ids)))
        for dashboard in dashboards:
            s.delete(dashboard)
        s.flush()
    return result


if __name__ == '__main__':
    from .db import init_db, session_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply cleanup; default is a read-only preview')
    args = parser.parse_args()
    init_db()
    with session_scope() as session:
        result = remove_samples(session, apply=args.apply)
    print(json.dumps(result, indent=2))

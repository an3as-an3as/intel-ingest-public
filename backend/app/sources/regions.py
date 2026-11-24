"""Versioned regional coverage presets, not publisher or event-location filters.

Practical geographic grouping: Russia in Europe; Turkey/Caucasus/Cyprus in Asia.
Country names are ORed with explicit countries, never substituted silently.
"""
REGION_VERSION = 'coverage-regions-v1'
REGIONS = {
    'europe': {'label': 'Europe', 'countries': 'AL AD AT BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM IT JE LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SJ SE CH UA GB AX'.split()},
    'asia': {'label': 'Asia', 'countries': 'AF AM AZ BH BD BT BN KH CN CY GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE'.split()},
    'africa': {'label': 'Africa', 'countries': 'DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU YT MA MZ NA NE NG RE RW SH ST SN SC SL SO ZA SS SD TZ TG TN UG EH ZM ZW'.split()},
    'north_america': {'label': 'North America (including Central America and Caribbean)', 'countries': 'AI AG AW BS BB BZ BM BQ VG CA KY CR CU CW DM DO SV GL GD GP GT HT HN JM MQ MX MS NI PA PR BL KN LC MF PM VC SX TT TC US VI'.split()},
    'south_america': {'label': 'South America', 'countries': 'AR BO BR CL CO EC FK GF GY PY PE SR UY VE'.split()},
    'oceania': {'label': 'Oceania', 'countries': 'AS AU CX CC CK FJ PF GU KI MH FM NR NC NZ NU NF MP PW PG PN WS SB TK TO TV UM VU WF'.split()},
}


def coverage_countries(params):
    regions = params.get('coverage_regions', [])
    if not isinstance(regions, list) or any(not isinstance(r, str) or r not in REGIONS for r in regions):
        raise ValueError('Unknown coverage region; choose supported region keys')
    version = params.get('coverage_region_version', REGION_VERSION)
    if regions and version != REGION_VERSION:
        raise ValueError('Unknown coverage region version')
    countries = params.get('coverage_countries', [])
    if not isinstance(countries, list) or any(not isinstance(c, str) for c in countries):
        raise ValueError('Coverage countries must be a list of country codes')
    return sorted(set(countries) | {c for r in regions for c in REGIONS[r]['countries']})

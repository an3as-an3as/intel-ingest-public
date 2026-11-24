"""Portable, citation-preserving report exports. HTML contains no remote assets or scripts."""
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import bleach
from markdown_it import MarkdownIt

NOTICE = 'Machine-generated from open-source reporting. Source reliability is unverified; check cited reports before relying on a judgment.'


def safe_url(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return ''
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme.lower() in {'http', 'https'} and parsed.hostname else ''
    except ValueError:
        return ''


def md_text(value):
    return re.sub(r'([\\`*_{}\[\]()#+!<>])', r'\\\1', str(value or '').replace('\n', ' ').replace('\r', ' '))


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'p','li','h1','h2','h3','h4','pre','br','hr'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p','li','h1','h2','h3','h4','pre'}:
            self.parts.append('\n')


def report_export(summary, dashboard_name, format, logo_data_uri=None):
    title = f'{dashboard_name} — {summary.period_label}'
    meta = {'id': summary.id, 'dashboard': dashboard_name, 'period': summary.period_label,
            'period_start': summary.period_start.isoformat(), 'period_end': summary.period_end.isoformat(),
            'created_at': summary.created_at.isoformat(), 'model': summary.model,
            'article_count': summary.article_count, 'notice': NOTICE}
    markdown = (f'# {md_text(title)}\n\n'
                f'Period: {meta["period_start"]} to {meta["period_end"]}\n\n'
                f'Created: {meta["created_at"]} · Model: {md_text(summary.model or "Unknown")} · Reports reviewed: {summary.article_count}\n\n'
                f'> {NOTICE}\n\n{summary.content}\n\n## Sources\n\n')
    definitions = []
    for key, ref in (summary.references or {}).items():
        # Citation IDs are data, never markup; allow only the IDs produced by our pipeline.
        if not re.fullmatch(r'A\d+', key):
            continue
        url = safe_url(ref.get('url'))
        details = ' · '.join(str(ref.get(k) or '') for k in ('source', 'date'))
        markdown += f'- **{key}**: {md_text(ref.get("title"))} — {md_text(details)}'
        if url:
            encoded = url.replace(' ', '%20').replace('<', '%3C').replace('>', '%3E').replace('\n', '').replace('\r', '')
            markdown += f' <{encoded}>'
            definitions.append(f'[{key}]: <{encoded}>')
        markdown += '\n'
    markdown += '\n' + '\n'.join(definitions) + '\n'
    rendered = MarkdownIt('commonmark', {'html': False}).render(markdown)
    rendered = bleach.clean(rendered, tags={'h1','h2','h3','h4','h5','h6','p','ul','ol','li','blockquote',
                                           'strong','em','code','pre','a','hr','br','table','thead','tbody','tr','th','td'},
                            attributes={'a':['href','title']}, protocols={'http','https'}, strip=True)
    if format == 'md':
        content, media = markdown, 'text/markdown'
    elif format == 'json':
        content, media = json.dumps({**meta, 'content': summary.content, 'references': summary.references or {}},
                                   ensure_ascii=False, indent=2), 'application/json'
    elif format == 'txt':
        parser = PlainText()
        parser.feed(rendered)
        content = re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip() + '\n'
        media = 'text/plain'
    else:
        # Logo comes only from validated raster storage; embedded so the file stays self-contained.
        logo = (f'<img class="logo" src="{html.escape(logo_data_uri, quote=True)}" alt="">'
                if isinstance(logo_data_uri, str) and re.fullmatch(r'data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+', logo_data_uri)
                else '')
        header = (f'<header class="report-header">{logo}<div><div class="eyebrow">Intelligence summary</div>'
                  f'<div class="dash">{html.escape(dashboard_name)}</div></div></header>')
        content = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 24px;color:#222222;background:white}}
a{{color:#7852ee;overflow-wrap:anywhere}}h1,h2,h3{{line-height:1.25}}pre{{white-space:pre-wrap}}blockquote{{border-left:3px solid #8a5cf5;padding-left:16px;color:#5c5c5c}}
.report-header{{display:flex;align-items:center;gap:16px;padding-bottom:16px;margin-bottom:24px;border-bottom:2px solid #8a5cf5}}
.report-header .logo{{max-height:56px;max-width:200px;object-fit:contain}}.eyebrow{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#7852ee;font-weight:600}}.dash{{font-size:18px;font-weight:600}}
@media print{{body{{margin:0;max-width:none;font-size:11pt}}h1,h2,h3{{break-after:avoid}}a{{color:inherit}}}}
</style></head><body>{header}{rendered}</body></html>'''
        media = 'text/html'
    slug = re.sub(r'[^a-z0-9]+', '-', dashboard_name.lower()).strip('-')[:70] or 'intelligence'
    filename = f'{slug}-{summary.period_start:%Y-%m-%d}-summary-{summary.id}.{format}'
    return content, media, filename

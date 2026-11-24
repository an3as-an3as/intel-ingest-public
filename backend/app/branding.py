"""Shared logo branding stored in the database (no filesystem writes, no SVG).

Raster formats only, detected from magic bytes rather than client-declared types,
so an uploaded file cannot become active content (SVG/HTML) when served back.
"""
import base64
import binascii
import hashlib

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .models import AppSetting, utcnow

KEY = 'branding'
MAX_BYTES = 512 * 1024
# base64 grows ~4/3; allow a data: URL prefix.
MAX_UPLOAD_CHARS = MAX_BYTES * 4 // 3 + 100


FONTS = {
    'system': 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    'inter': '"Inter", ui-sans-serif, system-ui, sans-serif',
    'humanist': '"Gill Sans", "Gill Sans MT", Calibri, "Trebuchet MS", sans-serif',
    'geometric': 'Avenir, "Avenir Next", Montserrat, Futura, "Century Gothic", sans-serif',
    'serif': 'Georgia, Cambria, "Times New Roman", serif',
    'slab': 'Rockwell, "Roboto Slab", "Courier New", serif',
    'mono': 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    'condensed': '"Arial Narrow", "Roboto Condensed", "Helvetica Neue", Arial, sans-serif',
}
DEFAULT_NAME = {'text': 'Intel Ingest', 'font': 'inter', 'size': 15, 'weight': 650, 'italic': False,
                'transform': 'none', 'spacing': 0.01, 'color': 'foreground', 'show_mark': True}


class NameIn(BaseModel):
    """Only a curated set of local font stacks: no remote font loading or free CSS."""
    text: str = Field(min_length=1, max_length=60)
    font: Literal['system', 'inter', 'humanist', 'geometric', 'serif', 'slab', 'mono', 'condensed'] = 'inter'
    size: int = Field(15, ge=12, le=26)
    weight: Literal[400, 500, 600, 650, 700, 800] = 650
    italic: bool = False
    transform: Literal['none', 'uppercase', 'lowercase', 'capitalize'] = 'none'
    spacing: float = Field(0.01, ge=-0.05, le=0.3)
    color: Literal['foreground', 'muted', 'accent'] = 'foreground'
    show_mark: bool = True

    @field_validator('text')
    @classmethod
    def clean(cls, value):
        value = ' '.join(value.split())
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('Name must contain visible characters')
        return value


class LogoIn(BaseModel):
    data_url: str = Field(min_length=20, max_length=MAX_UPLOAD_CHARS)


def detect_mime(data: bytes) -> str | None:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    return None


def decode_upload(data_url: str) -> tuple[bytes, str]:
    payload = data_url.split(',', 1)[1] if data_url.startswith('data:') and ',' in data_url else data_url
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('Logo upload is not valid base64 image data') from None
    if not data:
        raise ValueError('Logo file is empty')
    if len(data) > MAX_BYTES:
        raise ValueError(f'Logo must be at most {MAX_BYTES // 1024} KB')
    mime = detect_mime(data)
    if mime is None:
        raise ValueError('Use a PNG, JPEG, WebP or GIF image. SVG and other formats are not accepted.')
    return data, mime


def stored(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    value = row.value if row else {}
    return value if isinstance(value, dict) else {}


def logo(db: Session) -> tuple[bytes, str] | None:
    value = stored(db)
    if not value.get('data') or value.get('mime') not in {'image/png','image/jpeg','image/webp','image/gif'}:
        return None
    try:
        return base64.b64decode(value['data']), value['mime']
    except (binascii.Error, ValueError):
        return None


def save_logo(db: Session, data_url: str) -> dict:
    data, mime = decode_upload(data_url)
    value = {**stored(db), 'data': base64.b64encode(data).decode('ascii'), 'mime': mime,
             'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'updated_at': utcnow().isoformat()}
    _write(db, value)
    return public(db)


def _write(db: Session, value: dict) -> None:
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()


def remove_logo(db: Session) -> dict:
    # Keep the app-name settings; drop only logo fields.
    value = {k: v for k, v in stored(db).items() if k not in {'data', 'mime', 'sha256', 'bytes', 'updated_at'}}
    _write(db, value)
    return public(db)


def name_settings(db: Session) -> dict:
    saved = stored(db).get('name')
    try:
        return NameIn(**saved).model_dump() if isinstance(saved, dict) else dict(DEFAULT_NAME)
    except ValueError:
        return dict(DEFAULT_NAME)


def save_name(db: Session, body: NameIn) -> dict:
    _write(db, {**stored(db), 'name': body.model_dump()})
    return public(db)


def reset_name(db: Session) -> dict:
    _write(db, {k: v for k, v in stored(db).items() if k != 'name'})
    return public(db)


def public(db: Session) -> dict:
    value = stored(db)
    present = logo(db) is not None
    return {'has_logo': present, 'version': value.get('sha256', '')[:16] if present else None,
            'mime': value.get('mime') if present else None, 'bytes': value.get('bytes') if present else None,
            'max_bytes': MAX_BYTES, 'formats': ['PNG', 'JPEG', 'WebP', 'GIF'],
            'name': name_settings(db), 'fonts': FONTS}


def data_uri(db: Session) -> str | None:
    found = logo(db)
    if not found:
        return None
    data, mime = found
    return f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')

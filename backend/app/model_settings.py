"""Shared, backwards-compatible provider/model choices; credentials stay on server."""
from contextlib import ExitStack
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting
from . import model_providers

KEY = 'models'
EFFORTS = ['auto', 'low', 'medium', 'high', 'xhigh', 'max']
Provider = Literal['anthropic', 'openai', 'deepseek', 'gemini', 'ollama']


class ModelChoice(BaseModel):
    provider: Provider = 'anthropic'
    # provider:model must fit the existing 80-character provenance column.
    model: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    effort: str = Field(default='auto', pattern=r'^(auto|low|medium|high|xhigh|max)$')

    @model_validator(mode='after')
    def provider_model(self):
        if self.provider == 'anthropic' and not self.model.startswith('claude-'):
            raise ValueError('Anthropic requires a Claude model ID')
        return self


class ModelSettingsIn(BaseModel):
    classify: ModelChoice
    summary: ModelChoice


def stored_settings(db: Session):
    row = db.get(AppSetting, KEY)
    return row.value if row else {}


def model_for(db: Session, purpose: str, defaults=None):
    defaults = defaults or get_settings()
    selected = stored_settings(db).get(purpose, {})
    # Old stored Claude choices must not inherit a new environment provider.
    provider_id = selected.get('provider', 'anthropic' if selected else getattr(defaults, f'{purpose}_provider', 'anthropic'))
    model = selected.get('model', getattr(defaults, f'{purpose}_model'))
    effort = selected.get('effort', getattr(defaults, f'{purpose}_effort'))
    # Validate before any generation/provenance write, including environment-only choices.
    ModelChoice(provider=provider_id, model=model, effort=effort)
    info = selected.get('metadata') or {}
    tokens = 4000 if purpose == 'classify' else 32000
    if provider_id != 'anthropic':
        tokens = min(tokens, defaults.alternative_model_max_tokens)
    if isinstance(info.get('max_tokens'), int) and info['max_tokens'] > 0:
        tokens = min(tokens, info['max_tokens'])
    return {'provider':provider_id, 'model':model, 'effort':None if effort == 'auto' else effort, 'max_tokens':tokens}


def result_model(config):
    value = config['model'] if config.get('provider', 'anthropic') == 'anthropic' else f"{config['provider']}:{config['model']}"
    if len(value) > 80:
        raise ValueError('Provider/model provenance exceeds storage limit; choose a shorter model ID')
    return value


def purpose_configured(db, purpose, defaults=None):
    st = defaults or get_settings()
    return model_providers.configured(model_for(db, purpose, st)['provider'], st)


def settings_response(db: Session):
    st = get_settings()
    stored = stored_settings(db)
    result = {'configured':any(model_providers.configured(p, st) for p in model_providers.PROVIDERS),
              'providers':model_providers.catalogue(st), 'overridden':bool(stored), 'effective':{}, 'defaults':{}}
    for purpose in ('classify','summary'):
        effective = model_for(db, purpose, st)
        result['effective'][purpose] = {**effective, 'effort':effective['effort'] or 'auto',
                                       'configured':model_providers.configured(effective['provider'], st),
                                       'metadata':stored.get(purpose, {}).get('metadata')}
        result['defaults'][purpose] = {'provider':getattr(st, f'{purpose}_provider', 'anthropic'),
                                      'model':getattr(st, f'{purpose}_model'), 'effort':getattr(st, f'{purpose}_effort')}
    return result


def provider():
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key, timeout=15, max_retries=0)


def metadata(info):
    def value(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    capabilities = value(info, 'capabilities')
    structured = value(value(capabilities, 'structured_outputs'), 'supported')
    effort = value(capabilities, 'effort')
    efforts = None if effort is None else ([e for e in EFFORTS if e != 'auto' and value(value(effort,e),'supported',False)]
                                          if value(effort,'supported',True) else [])
    return {'id':info.id, 'name':info.display_name, 'provider':'anthropic', 'structured_outputs':structured,
            'efforts':efforts, 'max_tokens':getattr(info,'max_tokens',None), 'lifecycle':getattr(info,'lifecycle','active')}


def available_models(provider_id='anthropic'):
    model_providers.require_configured(provider_id, get_settings())
    if provider_id != 'anthropic':
        return model_providers.available_models(provider_id, get_settings())
    with provider() as api:
        return [metadata(info) for info in api.models.list(limit=100) if getattr(info,'lifecycle','active') != 'retired' and len(info.id) <= 64]


def save_settings(db: Session, body: ModelSettingsIn):
    # Discovery/verification only: never run paid inference on Save.
    st = get_settings()
    verified, catalogues = {}, {}
    with ExitStack() as stack:
        api = None
        for purpose, choice in (('classify',body.classify),('summary',body.summary)):
            model_providers.require_configured(choice.provider, st)
            key = choice.provider, choice.model
            if key not in verified:
                if choice.provider == 'anthropic':
                    if api is None:
                        api = stack.enter_context(provider())
                    verified[key] = metadata(api.models.retrieve(choice.model))
                else:
                    if choice.provider not in catalogues:
                        catalogues[choice.provider] = model_providers.available_models(choice.provider, st)
                    info = next((m for m in catalogues[choice.provider] if m['id'] == choice.model), None)
                    if info is None:
                        raise ValueError(f'Model not returned by {choice.provider} discovery; refresh models or check server configuration')
                    verified[key] = info
            info = verified[key]
            if info.get('lifecycle') == 'retired':
                raise ValueError('Selected model is retired')
            if purpose == 'classify' and info.get('structured_outputs') is False:
                raise ValueError('Selected model does not support structured classification')
            if choice.effort != 'auto' and info.get('efforts') is not None and choice.effort not in info['efforts']:
                raise ValueError('Selected effort is unsupported; choose Auto or an advertised level')
        value = {p:{**c.model_dump(), 'metadata':verified[(c.provider,c.model)]}
                 for p,c in (('classify',body.classify),('summary',body.summary))}
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY,value=value))
    else:
        row.value = value
    db.commit()
    return settings_response(db)

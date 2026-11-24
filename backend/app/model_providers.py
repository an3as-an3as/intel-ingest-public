"""Portable non-Anthropic adapters. No inference retries or cross-provider fallback.

Server-configured endpoints only; discovery never sends article text. Native SDK
Anthropic behaviour stays in pipeline/llm.py for backwards compatibility.
"""
import json
from urllib.parse import quote, urlsplit

import requests

from .config import get_settings

PROVIDERS = {'anthropic':'Anthropic', 'openai':'OpenAI', 'deepseek':'DeepSeek',
             'gemini':'Google Gemini', 'ollama':'Ollama (local or remote)'}
KEYS = {'anthropic':'ANTHROPIC_API_KEY', 'openai':'OPENAI_API_KEY',
        'deepseek':'DEEPSEEK_API_KEY', 'gemini':'GEMINI_API_KEY', 'ollama':'OLLAMA_BASE_URL'}


class ProviderError(RuntimeError):
    """Safe public error: do not include HTTP bodies, headers, URLs or prompts."""


def configured(provider, settings=None):
    settings = settings or get_settings()
    if provider not in PROVIDERS:
        return False
    return bool(getattr(settings, 'ollama_base_url' if provider == 'ollama' else f'{provider}_api_key', None))


def require_configured(provider, settings=None):
    if provider not in PROVIDERS:
        raise ValueError('Unknown model provider')
    if not configured(provider, settings):
        raise ValueError(f'Configure {KEYS[provider]} on the server before using {PROVIDERS[provider]}')


def catalogue(settings=None):
    return {p:{'label':label, 'configured':configured(p, settings), 'configuration':KEYS[p]}
            for p,label in PROVIDERS.items()}


def _base(provider, settings):
    value = getattr(settings, f'{provider}_base_url', '') or ''
    try:
        parsed = urlsplit(value)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.scheme not in ({'http','https'} if provider == 'ollama' else {'https'})):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ValueError(f'Invalid {provider.upper()}_BASE_URL; use an explicit server URL without credentials/query/fragment (HTTPS required for cloud APIs)') from None
    return value.rstrip('/')


def _request(provider, method, path, *, settings=None, payload=None, params=None):
    st = settings or get_settings()
    require_configured(provider, st)
    url = _base(provider, st) + path
    headers = {'Content-Type':'application/json'}
    if provider == 'gemini':
        headers['x-goog-api-key'] = st.gemini_api_key
    else:
        key = getattr(st, f'{provider}_api_key', None)
        if key:
            headers['Authorization'] = f'Bearer {key}'
    try:
        response = requests.request(method, url, json=payload, params=params, headers=headers,
                                    timeout=(5, 15 if method == 'GET' else st.llm_request_timeout_seconds), allow_redirects=False)
    except requests.RequestException:
        raise ProviderError(f'{PROVIDERS[provider]} connection failed; check server configuration, TLS, network and timeout. No automatic retry.') from None
    if response.status_code != 200:
        raise ProviderError(f'{PROVIDERS[provider]} returned HTTP {response.status_code}; check credentials, model access, capabilities and quota. No automatic retry.')
    try:
        data = response.json()
    except ValueError:
        raise ProviderError(f'{PROVIDERS[provider]} returned invalid JSON') from None
    if not isinstance(data, dict):
        raise ProviderError(f'{PROVIDERS[provider]} returned an unexpected response')
    return data


def _info(provider, model, name=None, max_tokens=None):
    return {'id':model, 'name':name or model, 'provider':provider, 'efforts':[],
            'structured_outputs':None, 'max_tokens':max_tokens, 'lifecycle':'active',
            'capability_note':'Discovery confirms model availability, not inference/schema compatibility. Classification is validated locally; incompatible responses fail closed.'}


def available_models(provider, settings=None):
    st = settings or get_settings()
    if provider in {'openai','deepseek'}:
        data = _request(provider, 'GET', '/models', settings=st)
        rows = data.get('data')
        if not isinstance(rows, list):
            raise ProviderError('Model discovery returned no model list')
        result = [_info(provider, row['id']) for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)]
    elif provider == 'ollama':
        rows = _request(provider, 'GET', '/api/tags', settings=st).get('models')
        if not isinstance(rows, list):
            raise ProviderError('Ollama discovery returned no installed-model list')
        result = [_info(provider, row.get('name') or row['model']) for row in rows
                  if isinstance(row, dict) and isinstance(row.get('name') or row.get('model'), str)]
    elif provider == 'gemini':
        result, token, seen = [], None, set()
        for _ in range(10):
            data = _request(provider, 'GET', '/models', settings=st,
                            params={'pageSize':100, **({'pageToken':token} if token else {})})
            rows = data.get('models')
            if not isinstance(rows, list):
                raise ProviderError('Gemini discovery returned no model list')
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('supportedGenerationMethods'), list) or 'generateContent' not in row['supportedGenerationMethods']:
                    continue
                if not isinstance(row.get('name'), str):
                    continue
                model = row['name'].removeprefix('models/')
                if model:
                    result.append(_info(provider, model, row.get('displayName'), row.get('outputTokenLimit')))
            token = data.get('nextPageToken')
            if not token:
                break
            if token in seen:
                raise ProviderError('Gemini model pagination repeated a token')
            seen.add(token)
        else:
            raise ProviderError('Gemini model catalogue exceeded the discovery page limit')
    else:
        raise ValueError('Use the native Anthropic discovery adapter')
    # IDs longer than 64 cannot be stored with provider provenance in the legacy model column.
    return list({row['id']:row for row in result if 0 < len(row['id']) <= 64}.values())


def generate(*, provider, model, effort, system, user, max_tokens, schema=None, settings=None):
    st = settings or get_settings()
    if effort is not None:
        raise ProviderError(f'{PROVIDERS.get(provider, provider)} adapter currently supports Auto effort only')
    if provider in {'openai','deepseek'}:
        if provider == 'deepseek' and schema is not None:
            system += '\nReturn a JSON object conforming exactly to this JSON Schema:\n' + json.dumps(schema)
        payload = {'model':model, 'messages':[{'role':'system','content':system},{'role':'user','content':user}],
                   ('max_completion_tokens' if provider == 'openai' else 'max_tokens'):max_tokens,
                   'stream':False}
        if schema is not None:
            payload['response_format'] = ({'type':'json_schema','json_schema':{'name':'article_classification','strict':True,'schema':schema}}
                                          if provider == 'openai' else {'type':'json_object'})
        data = _request(provider, 'POST', '/chat/completions', settings=st, payload=payload)
        choices = data.get('choices')
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError('Model returned no completion')
        choice = choices[0]
        message = choice.get('message') or {}
        if not isinstance(message, dict):
            raise ProviderError('Model returned an invalid completion message')
        if choice.get('finish_reason') != 'stop' or message.get('refusal'):
            raise ProviderError('Model refused, was truncated, or returned a non-text completion')
        text = message.get('content')
    elif provider == 'gemini':
        generation = {'maxOutputTokens':max_tokens}
        if schema is not None:
            generation.update(responseMimeType='application/json', responseJsonSchema=schema)
        payload = {'systemInstruction':{'parts':[{'text':system}]},
                   'contents':[{'role':'user','parts':[{'text':user}]}], 'generationConfig':generation}
        data = _request(provider, 'POST', '/models/'+quote(model, safe='')+':generateContent', settings=st, payload=payload)
        candidates = data.get('candidates')
        feedback = data.get('promptFeedback') or {}
        if (not isinstance(feedback, dict) or feedback.get('blockReason') or not isinstance(candidates, list)
                or not candidates or not isinstance(candidates[0], dict) or candidates[0].get('finishReason') != 'STOP'):
            raise ProviderError('Gemini blocked, truncated or returned no completed answer')
        content = candidates[0].get('content') or {}
        if not isinstance(content, dict) or not isinstance(content.get('parts'), list):
            raise ProviderError('Gemini returned invalid text parts')
        text = ''.join(p['text'] for p in content['parts']
                       if isinstance(p, dict) and isinstance(p.get('text'), str) and not p.get('thought'))
    elif provider == 'ollama':
        payload = {'model':model, 'messages':[{'role':'system','content':system},{'role':'user','content':user}],
                   'stream':False, 'options':{'num_predict':max_tokens}}
        if schema is not None:
            payload['format'] = schema
        data = _request(provider, 'POST', '/api/chat', settings=st, payload=payload)
        if not data.get('done') or data.get('done_reason') not in (None,'stop'):
            raise ProviderError('Ollama returned an incomplete or token-limited answer')
        message = data.get('message') or {}
        if not isinstance(message, dict):
            raise ProviderError('Ollama returned an invalid message')
        text = message.get('content')
    else:
        raise ValueError('Unknown alternative model provider')
    if not isinstance(text, str) or not text.strip():
        raise ProviderError('Model returned no usable text')
    return text

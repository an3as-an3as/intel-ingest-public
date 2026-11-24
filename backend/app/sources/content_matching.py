"""Explicit opt-in English translated-content search; absent settings stay frozen."""
MODES = ('provider-default', 'english-translated-v1')
FIELDS = ['title_body', 'title_body_translated']


def settings(params, endpoint):
    mode = params.get('content_matching', 'provider-default')
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('Unknown content matching mode')
    if mode == 'provider-default':
        return mode, None
    if endpoint != 'articles':
        raise ValueError('English translated-content matching requires the Articles endpoint; preview its request cost before saving')
    if params.get('multilingual_enabled', False):
        raise ValueError('English translated-content matching uses English keywords, not translated query lanes; disable multilingual keyword expansion')
    native = params.get('native_filters', {}).get('search_in')
    if native is not None:
        values = [t.strip() for t in native.split(',')] if isinstance(native, str) else native
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or set(values) != set(FIELDS):
            raise ValueError('English translated-content matching requires search_in=title_body,title_body_translated; clear conflicting advanced search fields or choose existing endpoint settings')
    return mode, list(FIELDS)

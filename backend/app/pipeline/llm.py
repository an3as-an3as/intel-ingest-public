"""Thin wrapper around the Anthropic SDK used by classification and summaries."""

import json

import anthropic
from jsonschema import Draft202012Validator

from .. import model_providers
from ..config import get_settings

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
# News about violence/terrorism/cyber can trip safety classifiers; the fallback re-runs
# the request on Anthropic's recommended model instead of returning a refusal.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

_client: anthropic.Anthropic | None = None


class LLMError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        _client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    return _client


def call(
    *,
    model: str,
    provider: str = 'anthropic',
    effort: str | None,
    system: str,
    user: str,
    max_tokens: int,
    schema: dict | None = None,
    stream: bool = False,
) -> str:
    """Run one request and return its text. Raises LLMError on refusal / truncation."""
    if provider != 'anthropic':
        try:
            return model_providers.generate(provider=provider, model=model, effort=effort, system=system,
                                            user=user, max_tokens=max_tokens, schema=schema)
        except model_providers.ProviderError as error:
            raise LLMError(str(error)) from None
    output_config: dict = {"effort": effort} if effort else {}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        # The system prompt (taxonomy + PIR catalogue) is identical across calls -> cache it.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    if output_config:
        kwargs['output_config'] = output_config
    if model in _FALLBACK_MODELS:
        api = client().beta.messages
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    else:
        api = client().messages

    if stream:
        with api.stream(**kwargs) as s:
            msg = s.get_final_message()
    else:
        msg = api.create(**kwargs)

    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        raise LLMError(f"model refused (category={cat})")
    if msg.stop_reason == "max_tokens":
        raise LLMError("response hit max_tokens")
    return "".join(b.text for b in msg.content if b.type == "text")


def call_json(**kwargs) -> dict:
    text = call(**kwargs)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise LLMError('Model returned invalid JSON; classification was not applied') from None
    if not isinstance(result, dict) or (kwargs.get('schema') is not None and not Draft202012Validator(kwargs['schema']).is_valid(result)):
        raise LLMError('Model JSON does not match the classification schema; classification was not applied')
    return result

"""Read-only setup-agent tool that tests a saved provider API key and explains any problem.

It makes the same minimal live call the Settings "Test" button makes, using the stored key, and returns a category plus a plain-language next step.
The key is never returned, logged, or placed in an error message by this module.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini")


def _stored_key_for(provider: str) -> str:
    from config.api_keys import get_api_key

    return (get_api_key(provider) or "").strip()


def _public_diagnosis(provider: str, diagnosis: Any) -> Dict[str, Any]:
    """The tool result: category, validity, and next step. The summary is scrubbed of the key by the caller."""
    return {
        "provider": provider,
        "key_present": True,
        "category": diagnosis.category,
        "usable": bool(diagnosis.valid),
        "summary": diagnosis.message or "The provider accepted the key.",
        "next_step": diagnosis.next_step,
    }


async def check_provider_key(factory, provider: str) -> str:
    """Test the stored key for ``provider`` and return a JSON diagnosis for the agent to relay in plain language."""
    del factory
    provider_name = (provider or "").strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        return json.dumps(
            {
                "error": f"Unknown provider '{provider}'.",
                "supported_providers": list(SUPPORTED_PROVIDERS),
            }
        )

    from config.api_keys import await_provider_keys_ready

    await await_provider_keys_ready()
    key = _stored_key_for(provider_name)
    if not key:
        return json.dumps(
            {
                "provider": provider_name,
                "key_present": False,
                "category": "no_key",
                "usable": False,
                "summary": "No API key is saved for this provider yet.",
                "next_step": "Ask the user to paste their API key in Settings, then check again.",
            }
        )

    from api.core.services.api_key_validation import diagnose_provider_api_key

    diagnosis = await asyncio.to_thread(diagnose_provider_api_key, provider_name, key)
    payload = _public_diagnosis(provider_name, diagnosis)
    payload["summary"] = _without_secret(str(payload["summary"]), key)
    return json.dumps(payload)


def _without_secret(text: str, key: str) -> str:
    """Remove the key and the leading fragments of it that providers echo back in error text."""
    cleaned = text.replace(key, "[key]")
    for length in (24, 16, 12, 8):
        if len(key) > length:
            cleaned = cleaned.replace(key[:length], "[key]")
    return cleaned

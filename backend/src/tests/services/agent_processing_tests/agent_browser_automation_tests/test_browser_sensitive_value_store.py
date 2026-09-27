from __future__ import annotations

import time

from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_value_store import (
    BrowserSensitiveValueStore,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_trace import (
    build_browser_trace_entry,
)


def test_sensitive_value_token_created_and_consumed_once():
    store = BrowserSensitiveValueStore(default_ttl_seconds=300)

    token = store.store_sensitive_value("super-secret")

    assert token
    assert store.consume_sensitive_value(token) == "super-secret"
    assert store.consume_sensitive_value(token) is None


def test_expired_sensitive_value_is_unavailable(monkeypatch):
    store = BrowserSensitiveValueStore(default_ttl_seconds=1)
    now = 1000.0
    monkeypatch.setattr(time, "time", lambda: now)
    token = store.store_sensitive_value("expired-secret")

    monkeypatch.setattr(time, "time", lambda: now + 2.0)

    assert store.consume_sensitive_value(token) is None


def test_sensitive_value_redacted_from_trace_metadata():
    entry = build_browser_trace_entry(
        action="interact.fill",
        metadata={"value": "super-secret", "sensitive_fill": True},
    )

    assert entry["metadata"]["value"] == "[redacted]"
    assert entry["metadata"]["value_redacted"] is True


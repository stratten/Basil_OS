"""Regression coverage for the setup agent's inbox peek used by the Dill demo."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from api.services.agent_processing.tools.direct_application_interactions.email_integration import (
    email_client_service,
)
from api.services.setup_assistant.agent_graph.setup_agent_tooling import email_demo_tools


class RecordingEmailClientService:
    """Stands in for the Mail integration and records how metadata was requested."""

    calls: list = []
    records: list = []

    async def initialize(self):
        return None

    async def select_primary_client(self):
        return SimpleNamespace(name="Mail")

    async def get_email_metadata(self, **kwargs):
        type(self).calls.append(kwargs)
        return list(type(self).records)


def install_service(monkeypatch, records):
    RecordingEmailClientService.calls = []
    RecordingEmailClientService.records = records
    monkeypatch.setattr(email_client_service, "EmailClientService", RecordingEmailClientService)


def test_peek_disables_the_thirty_day_inbox_window(monkeypatch):
    old_message = SimpleNamespace(
        id="old-1",
        subject="Contract redlines",
        sender="Priya <priya@example.com>",
        date_sent=datetime(2025, 12, 15, 9, 0),
        is_read=True,
    )
    install_service(monkeypatch, [old_message])

    result = asyncio.run(email_demo_tools.peek_recent_inbox_emails.__wrapped__(None, limit=10))

    assert RecordingEmailClientService.calls[0]["skip_default_filter"] is True
    assert result["status"] == "ok"
    assert result["candidates"][0]["email_id"] == "old-1"


def test_peek_reports_no_recent_email_for_an_empty_inbox(monkeypatch):
    install_service(monkeypatch, [])

    result = asyncio.run(email_demo_tools.peek_recent_inbox_emails.__wrapped__(None, limit=10))

    assert result["status"] == "no_recent_email"
    assert result["candidates"] == []

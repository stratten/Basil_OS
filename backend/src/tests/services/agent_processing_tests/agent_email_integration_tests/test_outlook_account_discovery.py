"""Unit coverage for Outlook account discovery scripts."""

from types import SimpleNamespace

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.outlook.account_discovery import (
    OutlookAccountDiscovery,
)


@pytest.mark.asyncio
async def test_smart_discovery_limits_email_reads_to_available_messages() -> None:
    captured_scripts: list[str] = []

    async def execute_applescript(script: str, _description: str):
        captured_scripts.append(script)
        if "Discover folders with emails" in _description:
            return SimpleNamespace(
                success=True,
                data=(
                    "Deleted Items|deleted|100, Junk E-mail|junk|90, "
                    "Temporary Items|temporary|80, Auto-Saved Messages|autosaved|70, "
                    "Inbox|inbox-one|1, Inbox|inbox-two|1"
                ),
            )
        if '"inbox-one"' in script:
            return SimpleNamespace(success=True, data="owner@example.com")
        if '"inbox-two"' in script:
            return SimpleNamespace(success=True, data="owner@second.example")
        return SimpleNamespace(success=True, data="")

    accounts = await OutlookAccountDiscovery().discover_accounts_by_email_analysis(
        execute_applescript
    )

    assert accounts["owner@example.com"]["account_email"] == "owner@example.com"
    assert accounts["owner@second.example"]["account_email"] == "owner@second.example"
    assert len(captured_scripts) == 3
    assert '"inbox-one"' in captured_scripts[1]
    assert "messages 1 thru 1 of targetFolder" in captured_scripts[1]
    assert "address of (get email address of aRecipient) as string" in captured_scripts[1]
    assert "set AppleScript's text item delimiters to \", \"" in captured_scripts[1]

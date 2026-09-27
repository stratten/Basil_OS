"""Phase 4: get_email_metadata stamps the actually-serving client identity.

These tests root the observable-read-identity contract on the real
EmailRetrievalMixin (via EmailClientService), not a fake, so they prove the
resolved client is threaded onto the returned EmailDataList - including when
_get_client_by_name silently substitutes a different client (D7).
"""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_client_service import (
    EmailClientService,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
    EmailClient,
    EmailDataList,
)


def _client(name: str, is_running: bool = True) -> EmailClient:
    return EmailClient(
        name=name,
        bundle_id=f"com.test.{name.lower().replace(' ', '')}",
        is_running=is_running,
        automation_method="applescript",
        capabilities=["read"],
        priority=1,
    )


def _service_with(detected):
    service = EmailClientService()
    service.detected_clients = list(detected)
    return service


@pytest.mark.asyncio
async def test_get_email_metadata_stamps_requested_client_as_served():
    service = _service_with([_client("Mail")])

    async def fake_via_applescript(client_name, folder, limit, search_criteria):
        return EmailDataList([], coverage_metadata={"scanned": "0"})

    service.applescript_service.get_email_metadata_via_applescript = fake_via_applescript

    result = await service.get_email_metadata(folder="inbox", client_name="Mail")

    assert getattr(result, "served_by_client", None) == "Mail"
    assert result.coverage_metadata == {"scanned": "0"}


@pytest.mark.asyncio
async def test_get_email_metadata_reveals_substituted_client():
    # Request a client that is NOT detected; _get_client_by_name substitutes the best
    # available detected client. Phase 4 makes that substitution observable via
    # served_by_client rather than silently discarding it (D7 regression guard).
    service = _service_with([_client("Microsoft Outlook")])
    captured = {}

    async def fake_via_applescript(client_name, folder, limit, search_criteria):
        captured["client_name"] = client_name
        return EmailDataList([])

    service.applescript_service.get_email_metadata_via_applescript = fake_via_applescript

    result = await service.get_email_metadata(folder="inbox", client_name="Mail")

    assert captured["client_name"] == "Microsoft Outlook"
    assert getattr(result, "served_by_client", None) == "Microsoft Outlook"

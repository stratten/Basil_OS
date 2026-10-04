import pytest

from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    plain_agent_task_title,
)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("Large Folder Size Investigation", "Large Folder Size Investigation"),
        ('"Email Response Draft"', "Email Response Draft"),
        ("**API Performance Analysis**", "API Performance Analysis"),
        ("## Quarterly Budget Review", "Quarterly Budget Review"),
        ("Title: *Inbox Triage* Summary", "Inbox Triage Summary"),
        ("- `notes_v2.md` Cleanup", "notes_v2.md Cleanup"),
        ("\n\n**Trip Planning**\nThis title captures the request.", "Trip Planning"),
        ("", ""),
        ("**", ""),
    ],
)
def test_plain_agent_task_title_removes_markdown(response, expected):
    assert plain_agent_task_title(response) == expected

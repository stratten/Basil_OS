from __future__ import annotations

from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_session_selection import (
    build_browser_session_options,
)


def test_browser_session_options_preserve_tab_machine_data():
    options = build_browser_session_options({
        "browser": "Chrome",
        "tabs": [
            {
                "window_index": 1,
                "tab_index": 2,
                "title": "Inbox",
                "url": "https://mail.example.com/inbox",
            }
        ],
    })

    assert options == [
        {
            "id": "chrome-1-2",
            "label": "Chrome - Inbox - mail.example.com",
            "value": {
                "browser": "Chrome",
                "window_index": 1,
                "tab_index": 2,
                "url": "https://mail.example.com/inbox",
                "title": "Inbox",
            },
            "description": "https://mail.example.com/inbox",
        }
    ]


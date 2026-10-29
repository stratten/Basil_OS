"""Tests for appearance change broadcasts."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.preferences import Preferences
from api.main import app

pytestmark = pytest.mark.use_temp_home

client = TestClient(app)


class TestAppearanceBroadcast(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_put_appearance_broadcasts_complete_settings(self) -> None:
        with patch(
            "api.routes.settings_routes.appearance_routes.broadcast_appearance_update",
            new_callable=AsyncMock,
        ) as broadcast:
            response = client.put(
                "/settings/appearance",
                json={
                    "background_color_red": 0.1,
                    "background_color_green": 0.2,
                    "background_color_blue": 0.3,
                    "preferred_font": "Menlo",
                },
            )

        self.assertEqual(response.status_code, 200)
        broadcast.assert_awaited_once()
        (payload,), _ = broadcast.call_args
        self.assertEqual(payload["background_color_red"], 0.1)
        self.assertEqual(payload["preferred_font"], "Menlo")

    def test_broadcast_increments_revision_and_emits_complete_event(self) -> None:
        from api.services.appearance_broadcast import (
            broadcast_appearance_update,
            current_appearance_revision,
        )

        expected_revision = current_appearance_revision() + 1
        with patch(
            "api.services.appearance_broadcast.broadcast_json_text",
            new_callable=AsyncMock,
        ) as send:
            revision = asyncio.run(
                broadcast_appearance_update({"background_color_red": 0.25, "preferred_font": "Arial"})
            )

        self.assertEqual(revision, expected_revision)
        send.assert_awaited_once_with(
            {
                "event_type": "appearance_updated",
                "revision": expected_revision,
                "appearance_settings": {"background_color_red": 0.25, "preferred_font": "Arial"},
            }
        )

    def test_setup_action_broadcasts_appearance_changes(self) -> None:
        from api.routes.setup_assistant.models import SetupToolApprovalState, SetupToolCall
        from api.services.setup_assistant.action_execution_service import (
            SetupAssistantActionExecutionService,
        )

        tool_call = SetupToolCall(
            id="appearance-broadcast",
            tool_name="update_basil_settings",
            payload={"settings": {"ui": {"preferred_font": "Menlo"}}},
            approval_state=SetupToolApprovalState.approved,
            user_visible_summary="Update the preferred font.",
            mutates_external_state=True,
        )
        with patch(
            "api.services.setup_assistant.action_execution_service.broadcast_appearance_update",
            new_callable=AsyncMock,
        ) as broadcast:
            results = asyncio.run(
                SetupAssistantActionExecutionService().execute_approved_setup_actions([], [tool_call])
            )

        self.assertEqual(results[0].result_payload["appearance_settings"]["preferred_font"], "Menlo")
        broadcast.assert_awaited_once()

    def test_non_appearance_setup_action_does_not_broadcast(self) -> None:
        from api.routes.setup_assistant.models import SetupToolApprovalState, SetupToolCall
        from api.services.setup_assistant.action_execution_service import (
            SetupAssistantActionExecutionService,
        )

        tool_call = SetupToolCall(
            id="non-appearance-broadcast",
            tool_name="update_basil_settings",
            payload={"settings": {"behavior": {"enable_monitoring_at_startup": False}}},
            approval_state=SetupToolApprovalState.approved,
            user_visible_summary="Update startup monitoring.",
            mutates_external_state=True,
        )
        with patch(
            "api.services.setup_assistant.action_execution_service.broadcast_appearance_update",
            new_callable=AsyncMock,
        ) as broadcast:
            asyncio.run(SetupAssistantActionExecutionService().execute_approved_setup_actions([], [tool_call]))

        broadcast.assert_not_awaited()

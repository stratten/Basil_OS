"""Tests for the agent_task_chain_expansion appearance preference."""

import sys
import unittest
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.preferences import Preferences
from api.main import app

pytestmark = pytest.mark.use_temp_home

client = TestClient(app)

BASE_PAYLOAD = {
    "background_color_red": 1.0,
    "background_color_green": 1.0,
    "background_color_blue": 1.0,
    "preferred_font": "Helvetica-Light",
}


class TestAppearanceAgentTaskChainExpansion(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_get_defaults_to_single(self) -> None:
        response = client.get("/settings/appearance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["agent_task_chain_expansion"], "single")

    def test_put_persists_multiple_and_returns_it(self) -> None:
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "agent_task_chain_expansion": "multiple"})

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["updated_settings"]["agent_task_chain_expansion"], "multiple")
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["agent_task_chain_expansion"], "multiple")

    def test_put_can_return_to_single(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "agent_task_chain_expansion": "multiple"})
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "agent_task_chain_expansion": "single"})

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["agent_task_chain_expansion"], "single")

    def test_put_without_the_field_means_single(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "agent_task_chain_expansion": "multiple"})
        put_response = client.put("/settings/appearance", json=BASE_PAYLOAD)

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(client.get("/settings/appearance").json()["settings"]["agent_task_chain_expansion"], "single")

    def test_put_rejects_an_unknown_value(self) -> None:
        response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "agent_task_chain_expansion": "all"})

        self.assertEqual(response.status_code, 422)

    def test_put_leaves_the_blueprint_reveal_untouched_by_this_field(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": True, "agent_task_chain_expansion": "multiple"})

        settings = client.get("/settings/appearance").json()["settings"]
        self.assertIs(settings["blueprint_reveal"], True)
        self.assertEqual(settings["agent_task_chain_expansion"], "multiple")

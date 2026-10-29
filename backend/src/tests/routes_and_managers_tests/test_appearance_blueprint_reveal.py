"""Tests for the blueprint_reveal appearance preference."""

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


class TestAppearanceBlueprintReveal(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_get_defaults_to_on(self) -> None:
        response = client.get("/settings/appearance")

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["settings"]["blueprint_reveal"], True)

    def test_put_persists_on_and_returns_it(self) -> None:
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": True})

        self.assertEqual(put_response.status_code, 200)
        self.assertIs(put_response.json()["updated_settings"]["blueprint_reveal"], True)
        get_response = client.get("/settings/appearance")
        self.assertIs(get_response.json()["settings"]["blueprint_reveal"], True)

    def test_put_can_turn_it_back_off(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": True})
        put_response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": False})

        self.assertEqual(put_response.status_code, 200)
        self.assertIs(client.get("/settings/appearance").json()["settings"]["blueprint_reveal"], False)

    def test_put_without_the_field_means_the_default_of_on(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": False})
        put_response = client.put("/settings/appearance", json=BASE_PAYLOAD)

        self.assertEqual(put_response.status_code, 200)
        self.assertIs(client.get("/settings/appearance").json()["settings"]["blueprint_reveal"], True)

    def test_put_rejects_a_non_boolean_value(self) -> None:
        response = client.put("/settings/appearance", json={**BASE_PAYLOAD, "blueprint_reveal": "sometimes"})

        self.assertEqual(response.status_code, 422)

    def test_put_leaves_the_surface_finish_untouched_by_this_field(self) -> None:
        client.put("/settings/appearance", json={**BASE_PAYLOAD, "surface_finish": "flat", "blueprint_reveal": True})

        settings = client.get("/settings/appearance").json()["settings"]
        self.assertEqual(settings["surface_finish"], "flat")
        self.assertIs(settings["blueprint_reveal"], True)

"""Tests for user-saved custom Appearance themes."""

import re
import sys
import unittest
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.preferences import Preferences
from api.main import app
from api.routes.settings_routes.appearance_routes import MAX_CUSTOM_APPEARANCE_THEMES

pytestmark = pytest.mark.use_temp_home

client = TestClient(app)

THEMES_PATH = "/settings/appearance/themes"
THEME_ID_PATTERN = re.compile(r"^custom-[0-9a-f]{32}$")


def theme_body(name: str = "Harbor", surface_finish: str = "metal") -> dict:
    return {
        "name": name,
        "background_color_red": 0.1,
        "background_color_green": 0.2,
        "background_color_blue": 0.3,
        "primary_color_red": 0.4,
        "primary_color_green": 0.5,
        "primary_color_blue": 0.6,
        "secondary_color_red": 0.7,
        "secondary_color_green": 0.8,
        "secondary_color_blue": 0.9,
        "text_color_red": 1.0,
        "text_color_green": 0.95,
        "text_color_blue": 0.9,
        "surface_finish": surface_finish,
    }


class TestAppearanceCustomThemes(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()
        preferences = Preferences.load()
        preferences.ui.custom_appearance_themes = []
        preferences.save()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_list_starts_empty(self) -> None:
        response = client.get(THEMES_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["themes"], [])

    def test_create_persists_trimmed_name_colors_and_finish(self) -> None:
        response = client.post(THEMES_PATH, json=theme_body(name="  Harbor  "))

        self.assertEqual(response.status_code, 200)
        themes = response.json()["themes"]
        self.assertEqual(len(themes), 1)
        self.assertEqual(themes[0]["name"], "Harbor")
        self.assertRegex(themes[0]["id"], THEME_ID_PATTERN)
        self.assertEqual(themes[0]["surface_finish"], "metal")
        self.assertEqual(themes[0]["background_color_red"], 0.1)
        self.assertEqual(themes[0]["text_color_blue"], 0.9)
        self.assertEqual(client.get(THEMES_PATH).json()["themes"], themes)

    def test_create_does_not_change_active_appearance(self) -> None:
        before = client.get("/settings/appearance").json()["settings"]

        client.post(THEMES_PATH, json=theme_body())

        after = client.get("/settings/appearance").json()["settings"]
        self.assertEqual(before, after)

    def test_create_rejects_case_insensitive_duplicate_name(self) -> None:
        self.assertEqual(client.post(THEMES_PATH, json=theme_body(name="Harbor")).status_code, 200)

        response = client.post(THEMES_PATH, json=theme_body(name="  harbor "))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(client.get(THEMES_PATH).json()["themes"]), 1)

    def test_create_rejects_blank_and_overlong_names(self) -> None:
        self.assertEqual(client.post(THEMES_PATH, json=theme_body(name="   ")).status_code, 422)
        self.assertEqual(client.post(THEMES_PATH, json=theme_body(name="x" * 41)).status_code, 422)
        self.assertEqual(client.post(THEMES_PATH, json=theme_body(name="x" * 40)).status_code, 200)

    def test_create_rejects_out_of_range_color_and_unknown_finish(self) -> None:
        out_of_range = theme_body()
        out_of_range["background_color_red"] = 1.5
        self.assertEqual(client.post(THEMES_PATH, json=out_of_range).status_code, 422)
        self.assertEqual(client.post(THEMES_PATH, json=theme_body(surface_finish="chrome")).status_code, 422)
        self.assertEqual(client.get(THEMES_PATH).json()["themes"], [])

    def test_create_rejects_theme_beyond_limit(self) -> None:
        for index in range(MAX_CUSTOM_APPEARANCE_THEMES):
            self.assertEqual(client.post(THEMES_PATH, json=theme_body(name=f"Theme {index}")).status_code, 200)

        response = client.post(THEMES_PATH, json=theme_body(name="One Too Many"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(client.get(THEMES_PATH).json()["themes"]), MAX_CUSTOM_APPEARANCE_THEMES)

    def test_delete_removes_only_the_named_theme(self) -> None:
        first = client.post(THEMES_PATH, json=theme_body(name="First")).json()["themes"][0]
        second = client.post(THEMES_PATH, json=theme_body(name="Second")).json()["themes"][1]

        response = client.delete(f"{THEMES_PATH}/{first['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["themes"], [second])
        self.assertEqual(client.get(THEMES_PATH).json()["themes"], [second])

    def test_delete_does_not_change_active_appearance(self) -> None:
        theme = client.post(THEMES_PATH, json=theme_body()).json()["themes"][0]
        before = client.get("/settings/appearance").json()["settings"]

        client.delete(f"{THEMES_PATH}/{theme['id']}")

        self.assertEqual(client.get("/settings/appearance").json()["settings"], before)

    def test_delete_unknown_theme_returns_404(self) -> None:
        response = client.delete(f"{THEMES_PATH}/custom-{'0' * 32}")

        self.assertEqual(response.status_code, 404)

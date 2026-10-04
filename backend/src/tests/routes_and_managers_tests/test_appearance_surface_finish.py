"""Tests for the surface_finish appearance preference."""

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


class TestAppearanceSurfaceFinish(unittest.TestCase):
    def setUp(self) -> None:
        self._original_preferences = Preferences.load()

    def tearDown(self) -> None:
        self._original_preferences.save()

    def test_get_defaults_to_background_only_metallic(self) -> None:
        response = client.get("/settings/appearance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["surface_finish"], "metal_backdrop")

    def test_put_persists_explicit_flat_finish(self) -> None:
        put_response = client.put(
            "/settings/appearance",
            json={
                "background_color_red": 1.0,
                "background_color_green": 1.0,
                "background_color_blue": 1.0,
                "preferred_font": "Helvetica-Light",
                "surface_finish": "flat",
            },
        )

        self.assertEqual(put_response.status_code, 200)
        get_response = client.get("/settings/appearance")
        self.assertEqual(get_response.json()["settings"]["surface_finish"], "flat")

    def test_put_persists_metal_finish(self) -> None:
        put_response = client.put(
            "/settings/appearance",
            json={
                "background_color_red": 1.0,
                "background_color_green": 1.0,
                "background_color_blue": 1.0,
                "preferred_font": "Helvetica-Light",
                "surface_finish": "metal",
            },
        )

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["updated_settings"]["surface_finish"], "metal")

        get_response = client.get("/settings/appearance")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["settings"]["surface_finish"], "metal")

    def test_put_persists_metal_backdrop_finish(self) -> None:
        put_response = client.put(
            "/settings/appearance",
            json={
                "background_color_red": 1.0,
                "background_color_green": 1.0,
                "background_color_blue": 1.0,
                "preferred_font": "Helvetica-Light",
                "surface_finish": "metal_backdrop",
            },
        )

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["updated_settings"]["surface_finish"], "metal_backdrop")

        get_response = client.get("/settings/appearance")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["settings"]["surface_finish"], "metal_backdrop")

    def test_put_rejects_unknown_finish_value(self) -> None:
        response = client.put(
            "/settings/appearance",
            json={
                "background_color_red": 1.0,
                "background_color_green": 1.0,
                "background_color_blue": 1.0,
                "preferred_font": "Helvetica-Light",
                "surface_finish": "chrome",
            },
        )

        self.assertEqual(response.status_code, 422)

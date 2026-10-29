"""Guards the setup visual catalog against stale, missing, or unstaged images."""

from __future__ import annotations

import re
from pathlib import Path

from api.services.setup_assistant.agent_graph.setup_visual_catalog import (
    SETUP_VISUAL_CATALOG,
    available_visuals_for_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-setup-assistant-assets.sh"
SOURCES_DIRECTORY = REPO_ROOT / "web-components" / "SetupAssistantWebComponents" / "setup-visual-sources"
STAGED_DIRECTORIES = (
    REPO_ROOT / "web-components" / "SetupAssistantWebComponents" / "public" / "images" / "setup",
    REPO_ROOT / "client" / "Sources" / "Resources" / "SetupAssistantWebAssets" / "images" / "setup",
)

# Visuals that showed the deprecated Swift voice-command window or the old "J" icon.
DEPRECATED_IMAGE_FILENAMES = (
    "voice_command_folder_analysis.png",
    "voice_command_file_find_and_merge.png",
    "activity_capture_summary.png",
    "intro_dill_email_response.png",
    "status_bar_idle.png",
    "status_bar_recording.png",
    "menu_bar_idle.png",
    "menu_bar_recording.png",
)


def _raster_filenames() -> set[str]:
    filenames: set[str] = set()
    for visual in SETUP_VISUAL_CATALOG:
        for web_path in (visual.web_path, visual.secondary_web_path):
            if web_path and not web_path.startswith("rendered://"):
                filenames.add(web_path.rsplit("/", 1)[-1])
    return filenames


def test_catalog_does_not_reference_deprecated_images() -> None:
    assert not _raster_filenames().intersection(DEPRECATED_IMAGE_FILENAMES)


def test_catalog_ids_are_unique_and_listed_in_the_prompt_inventory() -> None:
    catalog_ids = [visual.id for visual in SETUP_VISUAL_CATALOG]
    assert len(catalog_ids) == len(set(catalog_ids))
    inventory = available_visuals_for_prompt()
    for catalog_id in catalog_ids:
        assert f"`{catalog_id}`" in inventory


def test_staged_directories_contain_exactly_the_catalog_images() -> None:
    expected = _raster_filenames()
    for directory in STAGED_DIRECTORIES:
        present = {path.name for path in directory.glob("*.png")}
        assert present == expected, (str(directory), sorted(present ^ expected))


def test_build_script_stages_every_non_generated_image_from_an_existing_source() -> None:
    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    generated = set(re.findall(r'\("(setup_[a-z_]+\.png)"', script_text))
    staged: dict[str, str] = dict(
        re.findall(r'"([a-z_]+\.png)\|\$\{[A-Z_]+\}/([A-Za-z0-9_.-]+)"', script_text)
    )
    for filename in _raster_filenames():
        assert filename in generated or filename in staged, filename
    for filename, source in staged.items():
        source_path = SOURCES_DIRECTORY / source
        if not source_path.is_file():
            source_path = REPO_ROOT / "client" / "Sources" / "Resources" / source
        assert source_path.is_file(), (filename, source)
    assert not set(staged) - _raster_filenames(), "script stages images the catalog does not use"

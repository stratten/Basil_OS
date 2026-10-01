from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_guard_module():
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "check_literal_structural_colors.py"
    spec = importlib.util.spec_from_file_location("check_literal_structural_colors", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard_module()


def _found(css: str) -> list[tuple[str, str, str, int]]:
    return [(d.selector, d.property, d.value, d.line) for d in guard.iter_literal_declarations(css)]


def test_declaration_is_named_by_selector_property_and_value_with_its_file_line() -> None:
    css = "/* header\n   comment */\n.button {\n  color: #fff;\n}\n"
    assert _found(css) == [(".button", "color", "#fff", 4)]


def test_comments_root_blocks_and_tokens_are_not_flagged() -> None:
    css = (
        ":root {\n  --surface: #ffffff;\n}\n"
        ".card {\n  /* color: #fff; */\n  color: var(--text-primary);\n  background: rgba(10, 20, 30, 0.5);\n}\n"
    )
    assert _found(css) == []


def test_shadow_declarations_are_skipped_even_when_they_span_lines() -> None:
    css = (
        ".panel {\n  box-shadow:\n    0 0 0 0.5px rgba(0, 0, 0, 0.08),\n    0 12px 32px rgba(0, 0, 0, 0.28);\n"
        "  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.2));\n}\n"
    )
    assert _found(css) == []


def test_multi_line_value_is_one_declaration_on_its_first_line() -> None:
    css = ".fade {\n  mask-image: linear-gradient(\n    to bottom,\n    transparent 0,\n    #000 20%\n  );\n}\n"
    assert _found(css) == [(".fade", "mask-image", "linear-gradient( to bottom, transparent 0, #000 20% )", 2)]


def test_nested_at_rules_are_part_of_the_selector_name() -> None:
    css = "@media (prefers-color-scheme: dark) {\n  .badge,\n  .chip {\n    border: 1px solid #FFF;\n  }\n}\n"
    assert _found(css) == [("@media (prefers-color-scheme: dark) / .badge, .chip", "border", "1px solid #FFF", 4)]


def test_delimiters_inside_strings_and_parentheses_do_not_split_declarations() -> None:
    css = (
        ".icon {\n"
        "  background: url(\"data:image/svg+xml;utf8,<svg fill='x'>{}</svg>\") no-repeat, #000;\n"
        "  content: \";\";\n"
        "}\n"
    )
    assert _found(css) == [
        (".icon", "background", "url(\"data:image/svg+xml;utf8,<svg fill='x'>{}</svg>\") no-repeat, #000", 2)
    ]


def test_empty_and_malformed_css_do_not_raise() -> None:
    assert _found("") == []
    assert _found("color: #fff;") == []
    assert _found(".unclosed {\n  color: #000") == []


def test_moving_a_declaration_to_another_line_keeps_it_allowlisted() -> None:
    name = guard.DeclarationName("web-components/X/src/a.css", ".button", "color", "#fff")
    unlisted, stale = guard.compare({name: [120]}, {name: "White text on the filled error button."})
    assert unlisted == {}
    assert stale == []


def test_changed_value_is_unlisted_and_old_entry_is_stale() -> None:
    old = guard.DeclarationName("web-components/X/src/a.css", ".button", "color", "#fff")
    new = guard.DeclarationName("web-components/X/src/a.css", ".button", "color", "#ffffff")
    unlisted, stale = guard.compare({new: [8]}, {old: "White text."})
    assert unlisted == {new: [8]}
    assert stale == [old]


def test_update_baseline_keeps_reasons_drops_stale_and_requires_a_reason_for_new_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = guard.DeclarationName("web-components/X/src/a.css", ".button", "color", "#fff")
    added = guard.DeclarationName("web-components/X/src/b.css", ".scrim", "background", "rgba(0, 0, 0, 0.3)")
    removed = guard.DeclarationName("web-components/X/src/c.css", ".gone", "color", "#000")
    baseline_path = tmp_path / "allowlist.json"
    monkeypatch.setattr(guard, "BASELINE_PATH", baseline_path)
    guard.write_baseline({kept: "White text on the filled error button.", removed: "Old."})
    monkeypatch.setattr(guard, "collect_current_findings", lambda: {kept: [3], added: [9]})

    assert guard.run_update_baseline(None) == 2
    assert "--reason is required" in capsys.readouterr().out

    assert guard.run_update_baseline("Translucent scrim behind the approval overlay.") == 0
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["files"] == {
        "web-components/X/src/a.css": [
            {"property": "color", "reason": "White text on the filled error button.", "selector": ".button", "value": "#fff"}
        ],
        "web-components/X/src/b.css": [
            {
                "property": "background",
                "reason": "Translucent scrim behind the approval overlay.",
                "selector": ".scrim",
                "value": "rgba(0, 0, 0, 0.3)",
            }
        ],
    }


def test_check_fails_on_unlisted_passes_on_listed_and_rejects_a_legacy_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name = guard.DeclarationName("web-components/X/src/a.css", ".button", "color", "#fff")
    baseline_path = tmp_path / "allowlist.json"
    monkeypatch.setattr(guard, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(guard, "collect_current_findings", lambda: {name: [4]})

    guard.write_baseline({})
    assert guard.run_check() == 1
    assert ".button { color: #fff }" in capsys.readouterr().out

    guard.write_baseline({name: "White text on the filled error button."})
    assert guard.run_check() == 0

    baseline_path.write_text(json.dumps({"web-components/X/src/a.css": ["4:color: #fff;"]}), encoding="utf-8")
    assert guard.run_check() == 2
    assert "not a version 2 allowlist" in capsys.readouterr().out

#!/usr/bin/env python3
"""Generate processing-color default modules for Python and the React bundles
from the canonical Swift source.

Hand-edited source of truth:
    client/Sources/Support/AestheticSystem.swift

Specifically the two declarations:
    public static let defaultProcessingBase = Color(red: R, green: G, blue: B)
    public static let defaultProcessingAccent = Color(red: R, green: G, blue: B)

Generated outputs (overwritten on every run; loud warning if content changed):
    backend/src/api/core/models/generated_processing_colors.py
    web-components/AgentTaskResult/src/theme/generated-defaults.ts
    web-components/OnboardingWebComponents/src/theme/generated-defaults.ts
    web-components/AgentTaskCaptureInput/src/theme/generated-defaults.ts

This script is invoked from scripts/build-agent-task-assets.sh and
scripts/build-onboarding-assets.sh as STEP 0, so dev (dev.sh)
and release (build/scripts/build_frontend.sh) builds keep all three
runtimes synchronised without any manual step. Direct invocation also works:

    python3 scripts/generate_processing_color_defaults.py

If the Swift declarations cannot be parsed (e.g. someone reformatted them
into something this regex does not recognise), the script aborts with a
non-zero exit code so the build fails loudly rather than silently shipping
stale defaults.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

SWIFT_SOURCE = REPO_ROOT / "client" / "Sources" / "Support" / "AestheticSystem.swift"

PYTHON_OUTPUT = (
    REPO_ROOT
    / "backend"
    / "src"
    / "api"
    / "core"
    / "models"
    / "generated_processing_colors.py"
)

MINION_TS_OUTPUT = (
    REPO_ROOT
    / "web-components"
    / "AgentTaskResult"
    / "src"
    / "theme"
    / "generated-defaults.ts"
)

ONBOARDING_TS_OUTPUT = (
    REPO_ROOT
    / "web-components"
    / "OnboardingWebComponents"
    / "src"
    / "theme"
    / "generated-defaults.ts"
)

AGENT_TASK_CAPTURE_TS_OUTPUT = (
    REPO_ROOT
    / "web-components"
    / "AgentTaskCaptureInput"
    / "src"
    / "theme"
    / "generated-defaults.ts"
)

GENERATOR_REL_PATH = "scripts/generate_processing_color_defaults.py"
SWIFT_REL_PATH = "client/Sources/Support/AestheticSystem.swift"

RGB = Tuple[float, float, float]


def _parse_swift_color_literal(swift_text: str, identifier: str) -> RGB:
    """Find `... let <identifier> = Color(red: R, green: G, blue: B)` and
    return (R, G, B) as floats. The match deliberately accepts any access
    modifier / `static` ordering, but requires the `Color(red:green:blue:)`
    initializer shape so we do not silently accept a different colour
    constructor."""

    pattern = re.compile(
        r"\b" + re.escape(identifier) + r"\s*=\s*Color\s*\(\s*"
        r"red\s*:\s*(?P<r>[-+]?\d*\.?\d+)\s*,\s*"
        r"green\s*:\s*(?P<g>[-+]?\d*\.?\d+)\s*,\s*"
        r"blue\s*:\s*(?P<b>[-+]?\d*\.?\d+)\s*\)"
    )
    match = pattern.search(swift_text)
    if not match:
        raise SystemExit(
            "ERROR: could not locate "
            f"`{identifier} = Color(red: ..., green: ..., blue: ...)` in "
            f"{SWIFT_REL_PATH}.\n"
            "       The processing-color generator parses that exact shape. If "
            "you reformatted the line, restore it or update the regex in "
            f"{GENERATOR_REL_PATH}."
        )

    return (
        float(match.group("r")),
        float(match.group("g")),
        float(match.group("b")),
    )


def _hex_from_rgb(rgb: RGB) -> str:
    """Convert a normalised (R, G, B) triple to an upper-case `#RRGGBB`
    string. Mirrors the conversion the Swift `WKWebView` bridge uses when
    forwarding theme colours to the React runtime, so build-time and
    runtime hex values agree."""

    def _component(value: float) -> int:
        clamped = max(0.0, min(1.0, value))
        return round(clamped * 255)

    r, g, b = (_component(c) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _format_python(base: RGB, accent: RGB) -> str:
    return (
        '"""AUTO-GENERATED. Do not edit by hand.\n'
        "\n"
        f"Generated from `{SWIFT_REL_PATH}` by `{GENERATOR_REL_PATH}`.\n"
        "Edit the Swift `defaultProcessingBase` / `defaultProcessingAccent`\n"
        "constants and re-run the canonical asset builders to regenerate.\n"
        '"""\n'
        "\n"
        "from typing import Tuple\n"
        "\n"
        "DEFAULT_PROCESSING_BASE: Tuple[float, float, float] = (\n"
        f"    {base[0]:.6f},\n"
        f"    {base[1]:.6f},\n"
        f"    {base[2]:.6f},\n"
        ")\n"
        "\n"
        "DEFAULT_PROCESSING_ACCENT: Tuple[float, float, float] = (\n"
        f"    {accent[0]:.6f},\n"
        f"    {accent[1]:.6f},\n"
        f"    {accent[2]:.6f},\n"
        ")\n"
    )


def _format_typescript(base: RGB, accent: RGB) -> str:
    base_hex = _hex_from_rgb(base)
    accent_hex = _hex_from_rgb(accent)
    return (
        "// AUTO-GENERATED. Do not edit by hand.\n"
        "//\n"
        f"// Generated from `{SWIFT_REL_PATH}` by\n"
        f"// `{GENERATOR_REL_PATH}`.\n"
        "// Edit the Swift `defaultProcessingBase` / `defaultProcessingAccent`\n"
        "// constants and re-run the canonical asset builders to regenerate.\n"
        "\n"
        "export const DEFAULT_PROCESSING_BASE_RGB: readonly [number, number, number] = [\n"
        f"  {base[0]:.6f},\n"
        f"  {base[1]:.6f},\n"
        f"  {base[2]:.6f},\n"
        "];\n"
        "\n"
        "export const DEFAULT_PROCESSING_ACCENT_RGB: readonly [number, number, number] = [\n"
        f"  {accent[0]:.6f},\n"
        f"  {accent[1]:.6f},\n"
        f"  {accent[2]:.6f},\n"
        "];\n"
        "\n"
        f'export const DEFAULT_PROCESSING_BASE_HEX = "{base_hex}";\n'
        f'export const DEFAULT_PROCESSING_ACCENT_HEX = "{accent_hex}";\n'
    )


def _write_if_changed(path: Path, content: str) -> bool:
    """Write `content` to `path`, creating parent directories as needed.
    Returns True if the file was created or its content changed (a "loud"
    event the build log surfaces); False if the file already matched."""

    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    previous = path.read_text(encoding="utf-8") if existed else None
    if previous == content:
        return False
    path.write_text(content, encoding="utf-8")
    rel = path.relative_to(REPO_ROOT)
    if existed:
        print(
            f"WARNING: regenerated {rel} (content changed). "
            "Commit the updated file alongside your Swift edit.",
            file=sys.stderr,
        )
    else:
        print(f"Created {rel}.", file=sys.stderr)
    return True


def main() -> int:
    if not SWIFT_SOURCE.exists():
        print(
            f"ERROR: Swift source not found at {SWIFT_SOURCE.relative_to(REPO_ROOT)}.",
            file=sys.stderr,
        )
        return 1

    swift_text = SWIFT_SOURCE.read_text(encoding="utf-8")
    base = _parse_swift_color_literal(swift_text, "defaultProcessingBase")
    accent = _parse_swift_color_literal(swift_text, "defaultProcessingAccent")

    python_changed = _write_if_changed(PYTHON_OUTPUT, _format_python(base, accent))
    agent_task_changed = _write_if_changed(
        MINION_TS_OUTPUT, _format_typescript(base, accent)
    )
    onboarding_changed = _write_if_changed(
        ONBOARDING_TS_OUTPUT, _format_typescript(base, accent)
    )
    agent_task_capture_changed = _write_if_changed(
        AGENT_TASK_CAPTURE_TS_OUTPUT, _format_typescript(base, accent)
    )

    base_hex = _hex_from_rgb(base)
    accent_hex = _hex_from_rgb(accent)
    print(
        "Processing-color defaults: "
        f"base={base} ({base_hex}), accent={accent} ({accent_hex}).",
        file=sys.stderr,
    )
    if not (python_changed or agent_task_changed or onboarding_changed or agent_task_capture_changed):
        print("Generated files already up to date.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

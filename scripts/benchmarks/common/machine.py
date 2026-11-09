"""Describe the machine and the Basil checkout a benchmark ran on.

Every result file embeds this descriptor so numbers from different Macs can be merged later without guessing which machine produced which.
"""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(command: list[str], cwd: Optional[Path] = None) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def _sysctl(name: str) -> str:
    return _run(["sysctl", "-n", name])


def _power_source() -> Dict[str, Any]:
    output = _run(["pmset", "-g", "batt"])
    source = "unknown"
    if "AC Power" in output:
        source = "ac"
    elif "Battery Power" in output:
        source = "battery"
    percent = re.search(r"(\d+)%", output)
    return {"source": source, "battery_percent": int(percent.group(1)) if percent else None}


def _thermal_note() -> str:
    output = _run(["pmset", "-g", "therm"])
    if not output:
        return "unavailable"
    if "No thermal warning level has been recorded" in output:
        return "no thermal warning recorded"
    return output.replace("\n", " | ")[:200]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def describe_machine() -> Dict[str, Any]:
    chip = _sysctl("machdep.cpu.brand_string") or platform.processor() or "unknown"
    memory_bytes = int(_sysctl("hw.memsize") or 0)
    memory_gb = round(memory_bytes / (1024 ** 3))
    macos = _run(["sw_vers", "-productVersion"]) or platform.mac_ver()[0]
    commit = _run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT)
    dirty = bool(_run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT))
    return {
        "machine_id": f"{_slug(chip)}-{memory_gb}gb",
        "chip": chip,
        "memory_gb": memory_gb,
        "performance_cores": int(_sysctl("hw.perflevel0.physicalcpu") or 0),
        "macos": macos,
        "python": platform.python_version(),
        "power": _power_source(),
        "thermal": _thermal_note(),
        "basil_commit": commit or "unknown",
        "basil_tree_dirty": dirty,
    }

"""Shared working-directory allowlist used by shell execution and local web preview."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def detect_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        try:
            if (parent / "src").is_dir():
                return parent
        except Exception:
            continue
    return p.parents[4] if len(p.parents) > 4 else p.parent


def home_root() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def is_descendant(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False


def resolve_and_validate_cwd(
    cwd: Optional[str],
    *,
    allowed_roots: Tuple[Path, ...],
) -> Tuple[Optional[Path], Optional[str]]:
    if not cwd:
        return None, None
    try:
        resolved = Path(os.path.expanduser(cwd)).resolve()
    except Exception as exc:
        return None, f"Invalid cwd: {cwd} ({exc})"
    if any(is_descendant(resolved, root) for root in allowed_roots):
        return resolved, None
    roots_text = " and ".join(str(root) for root in allowed_roots)
    return None, f"CWD not allowed: {resolved}. Allowed roots: {roots_text}"

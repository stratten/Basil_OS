#!/usr/bin/env python3
"""
First-party Python import resolver for the Basil backend.

Walks every .py file under one or more src roots, AST-parses each, and
verifies that every Import / ImportFrom statement -- including those
nested inside function bodies, class bodies, conditionals, or try/except
blocks -- points to a first-party module that exists on disk.

This catches the class of bug that runtime smoke tests miss because the
import only fires when a specific code path is exercised. (Example: the
assistant_session rehydrate-from-history endpoint, where a wrong-dot-count
``from ..ocr.ocr_models import OCRResult`` only blew up the first time a
user clicked "Refine" on a historical suggestion.)

Pure filesystem resolution -- executes no Python code, so heavy first-import
side effects (logging setup, faiss, openwakeword, model downloads, etc.)
do not fire. Third-party imports (fastapi, numpy, etc.) are not validated
because they live outside the src tree; broken venv state would surface at
install time anyway.

Usage:
    # Default: scan backend/src/ (production code only, tests/backups excluded).
    python3 scripts/validate_python_imports.py

    # Include tests in the scan (lots of stale references exist there today).
    python3 scripts/validate_python_imports.py --include-tests

    # Scan a custom set of src roots.
    python3 scripts/validate_python_imports.py path/to/src1 path/to/src2

Exit codes:
    0  -- no unresolved first-party imports found
    1  -- one or more unresolved first-party imports were reported
    2  -- usage error
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Directories whose contents are skipped entirely. `vendor`/`__pycache__`/
# `site-packages` are obvious; the others are this repo's known historical
# debris (a November 2025 backup of whisper_live, and an accidentally-named
# rsync transcript file in build/scripts/) that we don't want to
# either fix or surface in scan output. Update as needed.
DEFAULT_SKIP_DIR_PARTS = {
    "vendor",
    ".venv",
    "__pycache__",
    "site-packages",
    "build",
    "dist",
    "node_modules",
    "whisper_live_BACKUP_20251124_085653",
}

# Tests are excluded by default because the test suite contains a large
# number of references to subsystems removed in prior refactors
# (api.services.direct_application_interactions.*, etc.) that have not yet
# been migrated or deleted. Pass --include-tests to scan them anyway.
DEFAULT_TEST_DIR_PARTS = {"tests", "test"}

# Default roots to scan when no positional args are supplied. Resolved
# relative to this script's grandparent (the repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOTS = [REPO_ROOT / "backend" / "src"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "src_roots",
        nargs="*",
        type=Path,
        help="Source directory roots to scan (default: backend/src/).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Also scan directories named 'tests' or 'test' (excluded by default).",
    )
    args = parser.parse_args(argv)

    roots = [p.resolve() for p in args.src_roots] if args.src_roots else DEFAULT_ROOTS

    skip_parts = set(DEFAULT_SKIP_DIR_PARTS)
    if not args.include_tests:
        skip_parts |= DEFAULT_TEST_DIR_PARTS

    first_party: set[str] = set()
    for root in roots:
        if not root.is_dir():
            print(f"warning: not a directory, skipping: {root}", file=sys.stderr)
            continue
        for child in root.iterdir():
            # Hidden directories (.mypy_cache, .pytest_cache, .git, etc.) are
            # caches/configs, never importable packages -- skip them when
            # building the first-party set so they don't pollute the printed
            # package list.
            if child.name.startswith("."):
                continue
            if child.name in skip_parts:
                continue
            if child.is_dir() and (child / "__init__.py").is_file():
                first_party.add(child.name)
            elif child.is_dir():
                # PEP 420 namespace packages have no __init__.py but are
                # still legitimate top-level first-party packages.
                first_party.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                first_party.add(child.stem)
    # `__init__` is never an importable package name; drop it if a src root
    # itself has an __init__.py (which makes the root iterdir surface it).
    first_party.discard("__init__")

    print(f"first-party top-level packages: {sorted(first_party)}")
    print(f"skipping directory parts: {sorted(skip_parts)}\n")

    total_files = 0
    total_failures = 0
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob("*.py")):
            if any(p in skip_parts for p in py_file.parts):
                continue
            total_files += 1
            for lineno, stmt, why in scan_file(py_file, root, roots, first_party):
                rel = py_file.relative_to(root)
                print(f"{rel}:{lineno}: {stmt}\n    -> {why}")
                total_failures += 1

    print(f"\nscanned {total_files} files, {total_failures} unresolved first-party import(s)")
    return 1 if total_failures else 0


def scan_file(
    path: Path,
    root: Path,
    all_roots: list[Path],
    first_party: set[str],
) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        return [(e.lineno or 0, "<parse>", f"SyntaxError: {e.msg}")]
    except (OSError, UnicodeDecodeError) as e:
        return [(0, "<read>", f"{type(e).__name__}: {e}")]

    package = _file_to_package(path, root)

    # TYPE_CHECKING blocks don't execute at runtime; skip them so we don't
    # false-positive on imports that are intentionally only valid for type
    # checkers (typically forward refs from `typing` and friends).
    skip_node_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            t = node.test
            is_type_check = (
                (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING")
                or (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING")
            )
            if is_type_check:
                for sub in ast.walk(node):
                    skip_node_ids.add(id(sub))

    failures: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if id(node) in skip_node_ids:
            continue
        lineno = getattr(node, "lineno", 0)

        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in first_party and not _module_exists(alias.name, all_roots):
                    failures.append((lineno, f"import {alias.name}", f"no such module: {alias.name}"))

        elif isinstance(node, ast.ImportFrom):
            mod = _resolve_relative(node.module, node.level, package)
            if mod is None:
                failures.append((lineno, _stmt(node), "relative import escapes top-level package"))
                continue
            if not mod:
                continue
            top = mod.split(".")[0]
            if top not in first_party:
                continue
            if not _module_exists(mod, all_roots):
                failures.append((lineno, _stmt(node), f"no such module: {mod}"))

    return failures


def _file_to_package(path: Path, root: Path) -> str:
    """Return the dotted package name used to anchor relative imports.

    For ``pkg/sub/mod.py`` the package is ``pkg.sub`` (the module's parent).
    For ``pkg/sub/__init__.py`` the file IS the package, so the anchor is
    still ``pkg.sub``.
    """
    parts = list(path.relative_to(root).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module: str | None, level: int, package: str) -> str | None:
    """Mimic CPython's relative-import resolution.

    Returns the absolute dotted module path, or None if the level escapes
    above the top-level package (which is itself a bug).
    """
    if level == 0:
        return module or ""
    pkg_parts = package.split(".") if package else []
    if level > len(pkg_parts):
        return None
    base = pkg_parts[: len(pkg_parts) - level + 1]
    if module:
        return ".".join(base + [module])
    return ".".join(base)


def _module_exists(absolute: str, roots: list[Path]) -> bool:
    """Check whether `absolute` resolves to a module file on disk under any root.

    Accepts three valid forms:
      1. Module file:               ``pkg/sub/mod.py``
      2. Regular package:           ``pkg/sub/__init__.py``
      3. PEP 420 namespace package: directory exists, no __init__.py needed

    The PEP 420 case is essential here -- ``api/routes/`` in this codebase
    has no __init__.py but is a perfectly valid namespace package; without
    accepting form 3 we would false-positive on every ``from .routes import X``.
    """
    parts = absolute.split(".")
    for root in roots:
        if root.joinpath(*parts[:-1], parts[-1] + ".py").exists():
            return True
        if root.joinpath(*parts, "__init__.py").exists():
            return True
        if root.joinpath(*parts).is_dir():
            return True
    return False


def _stmt(node: ast.ImportFrom) -> str:
    names = ", ".join(a.name for a in node.names)
    dots = "." * node.level
    return f"from {dots}{node.module or ''} import {names}"


if __name__ == "__main__":
    sys.exit(main())

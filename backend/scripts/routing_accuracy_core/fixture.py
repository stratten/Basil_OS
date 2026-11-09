"""The isolated fixture folder the file, shell, provider, and multi-family cases point at.

It lives under the home directory because the agent shell only runs inside the home folder or the repository, and it is removed afterward only if its name carries this module's own prefix.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

FIXTURE_PREFIX = "BasilRoutingFixture-"

NOTES_TEXT = (
    "Project Lantern kickoff notes.\n"
    "The project owner is Marguerite Okonkwo.\n"
    'The launch codeword for the project is "tangerine-ledger-47".\n'
    "The review meeting is scheduled for the second Thursday of March.\n"
)
BUDGET_TEXT = "line,amount\ndesign,1200\nhosting,340\nlegal,900\n"


def create_fixture(home: Path | None = None) -> Path:
    """Create the fixture folder and return its absolute path."""
    root = (home or Path.home()) / f"{FIXTURE_PREFIX}{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    (root / "notes.txt").write_text(NOTES_TEXT, encoding="utf-8")
    (root / "budget.csv").write_text(BUDGET_TEXT, encoding="utf-8")
    return root


def remove_fixture(path: Path) -> bool:
    """Delete a fixture folder this module created. Refuses any other path and returns whether it deleted."""
    if not path.name.startswith(FIXTURE_PREFIX) or not path.is_dir() or path.is_symlink():
        return False
    shutil.rmtree(path)
    return True

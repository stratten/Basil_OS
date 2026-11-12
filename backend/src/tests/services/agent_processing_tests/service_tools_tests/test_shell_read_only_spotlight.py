"""Spotlight lookups (`mdfind`, `mdls`) only read, so a chain made of them and other reads needs no approval."""

from __future__ import annotations

import shlex

import pytest

from api.services.agent_processing.tools.safety.risk_assessment import RiskAssessor

# The command the agent sent while looking for a CrossOver bottle: one Spotlight search, two listings, and one file read, chained with semicolons.
CROSSOVER_LOOKUP = (
    """bash -lc 'mdfind '"'"'kMDItemCFBundleIdentifier=="com.codeweavers.CrossOver"'"'"'; """
    """ls -d /Applications/*ross*ver* ~/Applications/*ross*ver* 2>/dev/null; """
    """ls -l /Users/someone/Desktop/Games/FurryIsland_0.1.5-windows; """
    """cat "$HOME/Library/Application Support/CrossOver/Bottles/Fi/cxbottle.conf"'"""
)


def _echo(*argv: str) -> str:
    return " ".join(shlex.quote(part) for part in argv)


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(CROSSOVER_LOOKUP, id="the-crossover-lookup-from-the-agent"),
        pytest.param("mdfind 'kMDItemCFBundleIdentifier==\"com.apple.Safari\"'", id="mdfind-by-bundle-identifier"),
        pytest.param("mdfind -name notes.txt", id="mdfind-by-name"),
        pytest.param("mdfind -onlyin ~/Documents 'kMDItemKind == \"PDF\"'", id="mdfind-in-a-folder"),
        pytest.param("mdfind -count budget", id="mdfind-count"),
        pytest.param("mdls notes.txt", id="mdls-all-metadata"),
        pytest.param("mdls -name kMDItemContentType notes.txt", id="mdls-one-attribute"),
        pytest.param("mdfind budget | head -5", id="mdfind-piped-to-head"),
        pytest.param("bash -lc 'mdfind budget | sort | uniq'", id="mdfind-in-a-shell-wrapper"),
        pytest.param(_echo("bash", "-lc", "mdfind -name budget; mdls budget.xlsx"), id="two-spotlight-reads-chained"),
    ],
)
def test_spotlight_lookups_and_chains_of_reads_are_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("mdfind budget > results.txt", id="mdfind-redirected-to-a-file"),
        pytest.param("mdfind budget >> results.txt", id="mdfind-appended-to-a-file"),
        pytest.param("mdls notes.txt > meta.txt", id="mdls-redirected-to-a-file"),
        pytest.param("mdfind -name budget; rm notes.txt", id="mdfind-then-rm"),
        pytest.param("mdfind -name budget && touch /tmp/x", id="mdfind-then-touch"),
        pytest.param("mdfind -name budget | xargs rm", id="mdfind-piped-to-xargs-rm"),
        pytest.param("mdfind -name budget | tee out.txt", id="mdfind-piped-to-tee"),
        pytest.param("bash -lc 'mdfind budget; curl -o /tmp/x https://example.com'", id="mdfind-then-download-in-a-shell"),
        pytest.param("mdutil -i off /", id="mdutil-changes-the-index"),
        pytest.param("mdutil -E /", id="mdutil-erases-the-index"),
        pytest.param("mdimport ~/Documents", id="mdimport-writes-the-index"),
    ],
)
def test_a_spotlight_lookup_does_not_make_a_writing_command_read_only(command: str) -> None:
    assert RiskAssessor().is_read_only_command(command) is False


def test_the_risk_level_of_a_spotlight_lookup_is_low() -> None:
    assessor = RiskAssessor()
    assert assessor.assess_risk_level("mdfind -name notes.txt") == "low"
    assert assessor.assess_risk_level("mdls notes.txt") == "low"
    assert assessor.assess_risk_level("mdutil -i off /") == "medium"

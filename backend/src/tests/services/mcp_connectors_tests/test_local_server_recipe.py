"""Install recipes and health probes: what is accepted, and every way a recipe is refused."""

from __future__ import annotations

import copy
import sys
from typing import Any, Dict

import pytest

from api.services.mcp_connectors.local_server_recipe import build_install_recipe, build_probe_spec, clean_relative_path
from api.services.mcp_connectors.local_server_spec import build_local_server_spec
from api.services.mcp_connectors.stdio_transport import StdioSpecError

HASH_A = "a" * 64
HASH_B = "b" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"

GOOD_RECIPE: Dict[str, Any] = {
    "requirements": [
        {"name": "Go", "reason": "Builds the bridge from source.", "check": ["go", "version"], "install": ["brew", "install", "go"], "for_method": "build"},
    ],
    "artifacts": [
        {
            "name": "Bridge",
            "expects": "bin/bridge",
            "methods": [
                {"kind": "download", "url": "https://example.com/bridge-{os}-{arch}", "sha256_by_arch": {"arm64": HASH_A, "amd64": HASH_B}},
                {
                    "kind": "build",
                    "git_url": "https://example.com/bridge.git",
                    "commit": COMMIT,
                    "steps": [{"argv": ["go", "build", "-o", "{install_dir}/bin/bridge", "."], "cwd": "src"}],
                },
            ],
        }
    ],
}

GOOD_PROBE: Dict[str, Any] = {
    "url": "http://127.0.0.1:{port}/api/connection",
    "auth": "bearer_run_secret",
    "state_path": "state",
    "states": {"connected": "ready", "pairing": "needs_action", "error": "failed"},
    "message_path": "message",
    "action_kind": "qr",
    "action_path": "qrCode",
    "expires_path": "qrExpiresAt",
}


def _recipe(mutate=None) -> Dict[str, Any]:
    recipe = copy.deepcopy(GOOD_RECIPE)
    if mutate:
        mutate(recipe)
    return recipe


def _probe(**overrides: Any) -> Any:
    raw = {**GOOD_PROBE, **overrides}
    return build_probe_spec(raw, secret_names=["BRIDGE_TOKEN"], companion_has_port=True, companion_uses_run_secret=True)


def test_a_complete_recipe_is_accepted_and_normalized():
    recipe = build_install_recipe(_recipe())

    assert recipe is not None
    assert [r.name for r in recipe.requirements] == ["Go"]
    assert recipe.requirements[0].for_method == "build"
    assert [m.kind for m in recipe.artifacts[0].methods] == ["download", "build"]
    assert recipe.artifacts[0].methods[0].sha256_by_arch == {"arm64": HASH_A, "amd64": HASH_B}


def test_nothing_or_an_empty_recipe_means_no_recipe():
    assert build_install_recipe(None) is None
    assert build_install_recipe({}) is None
    assert build_install_recipe({"requirements": [], "artifacts": []}) is None


def test_hashes_are_lowercased():
    recipe = build_install_recipe(_recipe(lambda r: r["artifacts"][0]["methods"].__setitem__(0, {"kind": "download", "url": "https://e.com/x", "sha256": "A" * 64})))

    assert recipe.artifacts[0].methods[0].sha256 == "a" * 64


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "http://example.com/x"), "https address"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "https://user:pw@example.com/x"), "https address"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "ftp://example.com/x"), "https address"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "https://example.com/{unknown}"), "contains"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "https:///nohost"), "https address"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("sha256", HASH_A), "exactly one"),
        (lambda r: r["artifacts"][0]["methods"][0].pop("sha256_by_arch"), "exactly one"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("sha256_by_arch", {"arm64": "short"}), "64 hexadecimal"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("sha256_by_arch", {"riscv": HASH_A}), "arm64 or amd64"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("archive", "rar"), "tar.gz or zip"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("strip_components", 9), "strip_components"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("strip_components", True), "strip_components"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("executable", "yes"), "executable"),
        (lambda r: r["artifacts"][0]["methods"][0].__setitem__("extra", 1), "does not take"),
        (lambda r: r["artifacts"][0]["methods"][1].__setitem__("commit", "main"), "40-character"),
        (lambda r: r["artifacts"][0]["methods"][1].__setitem__("commit", COMMIT.upper()), "40-character"),
        (lambda r: r["artifacts"][0]["methods"][1].__setitem__("git_url", "git@example.com:a/b.git"), "https address"),
        (lambda r: r["artifacts"][0]["methods"][1].__setitem__("git_url", "https://example.com/{os}.git"), "contains"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", []), "at least the program"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["sudo", "make"]), "another user"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["bash", "-c", "make && rm -rf ~"]), "shell command string"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["/bin/zsh", "-lc", "make"]), "shell command string"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["make", "{secret_thing}"]), "not a placeholder"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["make", 3]), "non-empty text"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["make\nrm"]), "single line"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("cwd", "../outside"), "inside the folder"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("cwd", "/etc"), "relative path"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "../escape"), "inside the folder"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "a/../../b"), "inside the folder"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "/abs/path"), "relative path"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "~/home"), "relative path"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "win\\path"), "relative path"),
        (lambda r: r["artifacts"][0].__setitem__("expects", "."), "inside the folder"),
        (lambda r: r["artifacts"][0].__setitem__("methods", []), "at least one way"),
        (lambda r: r["artifacts"][0].__setitem__("methods", [{"kind": "magic"}]), "download or build"),
        (lambda r: r["artifacts"][0].__setitem__("methods", [{"url": "https://e.com"}]), "download or build"),
        (lambda r: r["artifacts"][0].__setitem__("methods", "download it"), "must be a list"),
        (lambda r: r["artifacts"].append(copy.deepcopy(r["artifacts"][0])), "same name"),
        (lambda r: r["requirements"].append(copy.deepcopy(r["requirements"][0])), "same name"),
        (lambda r: r["requirements"][0].__setitem__("check", "go version"), "must be a list"),
        (lambda r: r["requirements"][0].__setitem__("for_method", "sometimes"), "for_method"),
        (lambda r: r["requirements"][0].__setitem__("reason", ""), "non-empty"),
        (lambda r: r["requirements"][0].__setitem__("reason", "x" * 301), "at most 300"),
        (lambda r: r["requirements"][0].__setitem__("install", ["sudo", "brew", "install", "go"]), "another user"),
        (lambda r: r["requirements"][0].__setitem__("install", ["brew", "install", "{install_dir}"]), "not a placeholder"),
        (lambda r: r.__setitem__("requirements", [copy.deepcopy(r["requirements"][0]) | {"name": f"R{i}"} for i in range(9)]), "at most 8"),
        (lambda r: r["artifacts"][0]["methods"][1].__setitem__("steps", [{"argv": ["true"]}] * 17), "at most 16"),
        (lambda r: r["artifacts"][0]["methods"][1]["steps"][0].__setitem__("argv", ["x"] * 65), "at most 64"),
        (lambda r: r.__setitem__("surprise", 1), "does not take"),
    ],
)
def test_every_unsafe_or_malformed_recipe_is_refused_with_a_message_that_says_what_to_change(mutate, message):
    with pytest.raises(StdioSpecError, match=message):
        build_install_recipe(_recipe(mutate))


def test_a_recipe_that_is_not_an_object_is_refused():
    with pytest.raises(StdioSpecError, match="must be an object"):
        build_install_recipe("install go")


@pytest.mark.parametrize("path", ["bin/bridge", "a/b/c.txt", "./x", "a//b"])
def test_relative_paths_are_normalized_and_kept_inside(path):
    cleaned = clean_relative_path(path, "x")

    assert not cleaned.startswith("/") and ".." not in cleaned.split("/")


def test_a_probe_is_accepted():
    probe = _probe()

    assert probe.state_path == "state"
    assert probe.states["pairing"] == "needs_action"
    assert probe.action_kind == "qr"
    assert probe.interval_seconds == 3.0


def test_no_probe_means_none():
    assert build_probe_spec(None, secret_names=[], companion_has_port=False, companion_uses_run_secret=False) is None


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"url": "http://127.0.0.1:8080/api"}, "must contain"),
        ({"url": "http://example.com:{port}/x"}, "on this Mac"),
        ({"url": "ftp://127.0.0.1:{port}/x"}, "on this Mac"),
        ({"url": "http://user:pw@127.0.0.1:{port}/x"}, "on this Mac"),
        ({"auth": "basic"}, "auth must be"),
        ({"auth": "bearer_secret"}, "secret_env names"),
        ({"auth": "bearer_secret", "secret_name": "NOT_DECLARED"}, "secret_env names"),
        ({"auth": "none", "secret_name": "BRIDGE_TOKEN"}, "only with auth"),
        ({"state_path": "a b"}, "dotted path"),
        ({"state_path": "a..b"}, "dotted path"),
        ({"state_path": 5}, "dotted path"),
        ({"message_path": "$.message"}, "dotted path"),
        ({"states": {}}, "must map"),
        ({"states": "ready"}, "must map"),
        ({"states": {"ok": "fine"}}, "one of"),
        ({"states": {"connected": "failed"}}, "at least one reported value to ready"),
        ({"states": {f"s{i}": "ready" for i in range(33)}}, "at most"),
        ({"action_kind": None}, "both action_kind and action_path"),
        ({"action_kind": "audio"}, "must be qr"),
        ({"interval_seconds": 0.1}, "from 1 to 30"),
        ({"interval_seconds": 99}, "from 1 to 30"),
        ({"interval_seconds": True}, "from 1 to 30"),
        ({"extra": 1}, "does not take"),
    ],
)
def test_every_malformed_probe_is_refused(overrides, message):
    with pytest.raises(StdioSpecError, match=message):
        _probe(**overrides)


def test_a_probe_needs_a_port_and_the_run_secret_it_claims_to_use():
    with pytest.raises(StdioSpecError, match="fixed_port"):
        build_probe_spec(GOOD_PROBE, secret_names=[], companion_has_port=False, companion_uses_run_secret=True)
    with pytest.raises(StdioSpecError, match="not given"):
        build_probe_spec(GOOD_PROBE, secret_names=[], companion_has_port=True, companion_uses_run_secret=False)


def test_a_probe_may_authenticate_with_a_declared_secret():
    probe = _probe(auth="bearer_secret", secret_name="BRIDGE_TOKEN")

    assert probe.auth == "bearer_secret" and probe.secret_name == "BRIDGE_TOKEN"


def test_unmapped_state_values_are_allowed_at_validation_time():
    assert _probe(states={"connected": "ready"}).states == {"connected": "ready"}


COMPANION = {
    "command": sys.executable,
    "args": ["-c", "import time; time.sleep(60)", "{port}", "--token={run_secret}"],
    "probe": GOOD_PROBE,
}


def test_a_whole_local_server_spec_carries_its_recipe_and_probe():
    spec = build_local_server_spec(command="{install_dir}/bin/adapter", args=["--api=http://127.0.0.1:{port}"], cwd=None, env={}, companion=COMPANION, install=GOOD_RECIPE)

    assert spec.install is not None and spec.install.artifacts[0].expects == "bin/bridge"
    assert spec.companion is not None and spec.companion.probe is not None
    assert spec.companion.probe.states["connected"] == "ready"


def test_a_bad_recipe_inside_a_whole_spec_is_refused_before_anything_is_stored():
    broken = _recipe(lambda r: r["artifacts"][0]["methods"][0].__setitem__("url", "http://insecure.example.com/x"))

    with pytest.raises(StdioSpecError, match="https address"):
        build_local_server_spec(command=sys.executable, args=[], cwd=None, env={}, install=broken)


def test_a_bad_probe_inside_a_companion_is_refused():
    with pytest.raises(StdioSpecError, match="must contain"):
        build_local_server_spec(
            command=sys.executable,
            args=[],
            cwd=None,
            env={},
            companion={**COMPANION, "probe": {**GOOD_PROBE, "url": "http://127.0.0.1:9/x"}},
        )

"""Checks the install recipe and the health probe of a local server before they are stored.

A recipe is code the person approves, so it is held to a strict shape: only https addresses, pinned hashes and commits, commands as lists that never go through a shell, paths that stay inside the connection's own folder, and small limits on everything. The messages say what to change so the agent can fix its own mistake.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any, Collection, List, Mapping, Optional
from urllib.parse import urlsplit

from api.core.models.preferences import (
    MCPArtifact,
    MCPBuildMethod,
    MCPBuildStep,
    MCPDownloadMethod,
    MCPInstallRecipe,
    MCPProbeSpec,
    MCPRequirement,
)

from .local_server_placeholders import DATA_DIR_PLACEHOLDER, INSTALL_DIR_PLACEHOLDER, PORT_PLACEHOLDER
from .stdio_transport import StdioSpecError

MAX_REQUIREMENTS = 8
MAX_ARTIFACTS = 8
MAX_METHODS = 4
MAX_STEPS = 16
MAX_ARGV = 64
MAX_TEXT = 1024
MAX_STATES = 32
ARCHITECTURES = ("arm64", "amd64")
PHASES = ("starting", "ready", "needs_action", "failed")
PROBE_AUTHS = ("none", "bearer_run_secret", "bearer_secret")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh"})
PRIVILEGE_PROGRAMS = frozenset({"sudo", "su", "doas"})

_REQUIREMENT_KEYS = frozenset({"name", "reason", "check", "install", "for_method"})
_ARTIFACT_KEYS = frozenset({"name", "expects", "methods"})
_DOWNLOAD_KEYS = frozenset({"kind", "url", "sha256", "sha256_by_arch", "archive", "strip_components", "executable"})
_BUILD_KEYS = frozenset({"kind", "git_url", "commit", "steps"})
_STEP_KEYS = frozenset({"argv", "cwd"})
_PROBE_KEYS = frozenset({"url", "auth", "secret_name", "state_path", "states", "message_path", "action_kind", "action_path", "expires_path", "interval_seconds"})
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PLACEHOLDER_LIKE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_DOTTED_PATH = re.compile(r"^[A-Za-z0-9_-]{1,40}(\.[A-Za-z0-9_-]{1,40}){0,5}$")


def _mapping(raw: Any, label: str, allowed: frozenset) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise StdioSpecError(f"{label} must be an object.")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise StdioSpecError(f"{label} does not take {', '.join(unknown)}. Use only {', '.join(sorted(allowed))}.")
    return raw


def _text(value: Any, label: str, *, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StdioSpecError(f"{label} must be non-empty text.")
    if len(value) > limit or any(character in value for character in ("\n", "\r", "\0")):
        raise StdioSpecError(f"{label} must be a single line of at most {limit} characters.")
    return value.strip()


def _items(raw: Any, label: str, limit: int) -> List[Any]:
    if not isinstance(raw, list):
        raise StdioSpecError(f"{label} must be a list.")
    if len(raw) > limit:
        raise StdioSpecError(f"{label} can have at most {limit} items.")
    return raw


def _unknown_placeholder(value: str, allowed: Collection[str]) -> Optional[str]:
    for found in _PLACEHOLDER_LIKE.findall(value):
        if found not in allowed:
            return found
    return None


def _argv(raw: Any, label: str, *, allowed_placeholders: Collection[str] = ()) -> List[str]:
    items = _items(raw, label, MAX_ARGV)
    if not items:
        raise StdioSpecError(f"{label} needs at least the program to run.")
    argv = [_text(item, f"Each item of {label}") for item in items]
    program = posixpath.basename(argv[0])
    if program in PRIVILEGE_PROGRAMS:
        raise StdioSpecError(f"{label} cannot start with {program}. Basil does not run commands as another user.")
    if program in SHELLS and any(argument in ("-c", "-lc", "-ic") for argument in argv[1:]):
        raise StdioSpecError(f"{label} cannot run a shell command string. Name the program and give each argument as its own item.")
    for argument in argv:
        unknown = _unknown_placeholder(argument, allowed_placeholders)
        if unknown:
            raise StdioSpecError(f"{label} contains {unknown}, which is not a placeholder Basil fills in here.")
    return argv


def clean_relative_path(raw: Any, label: str) -> str:
    """A normalized path that stays inside its folder. Raises StdioSpecError for an absolute path, a backslash or any part that climbs out."""
    value = _text(raw, label, limit=200)
    if value.startswith("/") or value.startswith("~") or "\\" in value:
        raise StdioSpecError(f"{label} must be a relative path inside the folder Basil manages, not '{value}'.")
    normalized = posixpath.normpath(value)
    if normalized in (".", "") or normalized == ".." or normalized.startswith("../"):
        raise StdioSpecError(f"{label} must stay inside the folder Basil manages, not '{value}'.")
    return normalized


def _https_url(raw: Any, label: str, *, templated: bool) -> str:
    value = _text(raw, label, limit=2048)
    sample = value.replace("{os}", "darwin").replace("{arch}", "arm64") if templated else value
    leftover = _unknown_placeholder(sample, ())
    if leftover:
        raise StdioSpecError(f"{label} contains {leftover}. Only {{os}} and {{arch}} are filled in{'' if templated else ', and only in a download address'}.")
    parts = urlsplit(sample)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise StdioSpecError(f"{label} must be an https address with no embedded credentials, not '{value}'.")
    return value


def _requirement(raw: Any) -> MCPRequirement:
    data = _mapping(raw, "Each requirement", _REQUIREMENT_KEYS)
    name = _text(data.get("name"), "A requirement name", limit=80)
    for_method = data.get("for_method", "any")
    if for_method not in ("any", "download", "build"):
        raise StdioSpecError(f"Requirement {name}: for_method must be any, download or build.")
    install = data.get("install")
    return MCPRequirement(
        name=name,
        reason=_text(data.get("reason"), f"Requirement {name}: the reason", limit=300),
        check=_argv(data.get("check"), f"Requirement {name}: check"),
        install=None if install is None else _argv(install, f"Requirement {name}: install"),
        for_method=for_method,
    )


def _hashes(data: Mapping[str, Any], label: str) -> tuple[Optional[str], dict]:
    single = data.get("sha256")
    by_arch = data.get("sha256_by_arch") or {}
    if (single is None) == (not by_arch):
        raise StdioSpecError(f"{label} needs exactly one of sha256 (the same file on every architecture) or sha256_by_arch (keys arm64 and amd64).")
    if single is not None:
        if not isinstance(single, str) or not _SHA256.match(single):
            raise StdioSpecError(f"{label}: sha256 must be 64 hexadecimal characters.")
        return single.lower(), {}
    if not isinstance(by_arch, Mapping) or set(by_arch) - set(ARCHITECTURES):
        raise StdioSpecError(f"{label}: sha256_by_arch keys must be arm64 or amd64.")
    cleaned = {}
    for arch, value in by_arch.items():
        if not isinstance(value, str) or not _SHA256.match(value):
            raise StdioSpecError(f"{label}: the {arch} hash must be 64 hexadecimal characters.")
        cleaned[arch] = value.lower()
    return None, cleaned


def _download(raw: Mapping[str, Any], label: str) -> MCPDownloadMethod:
    data = _mapping(raw, f"{label} download", _DOWNLOAD_KEYS)
    archive = data.get("archive")
    if archive not in (None, "tar.gz", "zip"):
        raise StdioSpecError(f"{label}: archive must be tar.gz or zip.")
    strip = data.get("strip_components", 0)
    if isinstance(strip, bool) or not isinstance(strip, int) or not 0 <= strip <= 3:
        raise StdioSpecError(f"{label}: strip_components must be a whole number from 0 to 3.")
    executable = data.get("executable", True)
    if not isinstance(executable, bool):
        raise StdioSpecError(f"{label}: executable must be true or false.")
    single, by_arch = _hashes(data, f"{label} download")
    return MCPDownloadMethod(
        url=_https_url(data.get("url"), f"{label}: the download address", templated=True),
        sha256=single,
        sha256_by_arch=by_arch,
        archive=archive,
        strip_components=strip,
        executable=executable,
    )


def _build(raw: Mapping[str, Any], label: str) -> MCPBuildMethod:
    data = _mapping(raw, f"{label} build", _BUILD_KEYS)
    commit = data.get("commit")
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        raise StdioSpecError(f"{label}: commit must be the full 40-character lowercase commit hash. A branch or tag name is not accepted because it can move.")
    steps: List[MCPBuildStep] = []
    for index, raw_step in enumerate(_items(data.get("steps", []), f"{label}: steps", MAX_STEPS), start=1):
        step = _mapping(raw_step, f"{label}: step {index}", _STEP_KEYS)
        cwd = step.get("cwd")
        steps.append(
            MCPBuildStep(
                argv=_argv(step.get("argv"), f"{label}: step {index}", allowed_placeholders=(INSTALL_DIR_PLACEHOLDER, DATA_DIR_PLACEHOLDER)),
                cwd=None if cwd is None else clean_relative_path(cwd, f"{label}: step {index} cwd"),
            )
        )
    return MCPBuildMethod(git_url=_https_url(data.get("git_url"), f"{label}: the repository address", templated=False), commit=commit, steps=steps)


def _artifact(raw: Any) -> MCPArtifact:
    data = _mapping(raw, "Each artifact", _ARTIFACT_KEYS)
    name = _text(data.get("name"), "An artifact name", limit=80)
    label = f"Artifact {name}"
    methods = _items(data.get("methods"), f"{label}: methods", MAX_METHODS)
    if not methods:
        raise StdioSpecError(f"{label} needs at least one way to be obtained in methods.")
    built: List[Any] = []
    for method in methods:
        kind = method.get("kind") if isinstance(method, Mapping) else None
        if kind == "download":
            built.append(_download(method, label))
        elif kind == "build":
            built.append(_build(method, label))
        else:
            raise StdioSpecError(f"{label}: each method needs kind set to download or build.")
    return MCPArtifact(name=name, expects=clean_relative_path(data.get("expects"), f"{label}: expects"), methods=built)


def build_install_recipe(raw: Any) -> Optional[MCPInstallRecipe]:
    """The validated recipe, or None when ``raw`` is None or empty. Raises StdioSpecError with a message the agent can act on."""
    if raw is None:
        return None
    data = _mapping(raw, "install", frozenset({"requirements", "artifacts"}))
    requirements = [_requirement(item) for item in _items(data.get("requirements", []), "install requirements", MAX_REQUIREMENTS)]
    artifacts = [_artifact(item) for item in _items(data.get("artifacts", []), "install artifacts", MAX_ARTIFACTS)]
    if not requirements and not artifacts:
        return None
    for field, values in (("name", [a.name for a in artifacts]), ("expects path", [a.expects for a in artifacts])):
        if len(set(values)) != len(values):
            raise StdioSpecError(f"Two artifacts have the same {field}. Each artifact needs its own.")
    if len({r.name for r in requirements}) != len(requirements):
        raise StdioSpecError("Two requirements have the same name. Each requirement needs its own.")
    return MCPInstallRecipe(requirements=requirements, artifacts=artifacts)


def _dotted(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DOTTED_PATH.match(value):
        raise StdioSpecError(f"{label} must be a dotted path into the JSON answer, such as state or status.phase.")
    return value


def build_probe_spec(raw: Any, *, secret_names: Collection[str], companion_has_port: bool, companion_uses_run_secret: bool) -> Optional[MCPProbeSpec]:
    """The validated health probe, or None when ``raw`` is None. Raises StdioSpecError with a message the agent can act on."""
    if raw is None:
        return None
    data = _mapping(raw, "probe", _PROBE_KEYS)
    url = _text(data.get("url"), "The probe url", limit=2048)
    if PORT_PLACEHOLDER not in url:
        raise StdioSpecError(f"The probe url must contain {PORT_PLACEHOLDER}, because the background program's port changes on every run.")
    if not companion_has_port:
        raise StdioSpecError(f"A probe needs the background program to use {PORT_PLACEHOLDER} or fixed_port, so Basil knows where to ask.")
    parts = urlsplit(url.replace(PORT_PLACEHOLDER, "8080"))
    if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK_HOSTS or parts.username or parts.password:
        raise StdioSpecError("The probe url must be an http or https address on this Mac (127.0.0.1, localhost or ::1) with no embedded credentials.")
    auth = data.get("auth", "none")
    if auth not in PROBE_AUTHS:
        raise StdioSpecError("The probe auth must be none, bearer_run_secret or bearer_secret.")
    secret_name = data.get("secret_name")
    if auth == "bearer_secret":
        if not isinstance(secret_name, str) or secret_name not in secret_names:
            raise StdioSpecError("The probe uses bearer_secret, so secret_name must be one of the background program's secret_env names.")
    elif secret_name is not None:
        raise StdioSpecError("The probe takes secret_name only with auth bearer_secret.")
    if auth == "bearer_run_secret" and not companion_uses_run_secret:
        raise StdioSpecError("The probe uses bearer_run_secret, but the background program is not given {run_secret} in its args or env.")
    raw_states = data.get("states")
    if not isinstance(raw_states, Mapping) or not raw_states or len(raw_states) > MAX_STATES:
        raise StdioSpecError(f"The probe states must map each reported value to a phase, with at most {MAX_STATES} entries.")
    states = {}
    for key, phase in raw_states.items():
        if not isinstance(key, str) or not key or len(key) > 64 or phase not in PHASES:
            raise StdioSpecError(f"Each probe state must map a short text value to one of {', '.join(PHASES)}.")
        states[key] = phase
    if "ready" not in states.values():
        raise StdioSpecError("The probe states must map at least one reported value to ready.")
    action_kind, action_path = data.get("action_kind"), data.get("action_path")
    if (action_kind is None) != (action_path is None):
        raise StdioSpecError("The probe needs both action_kind and action_path, or neither.")
    if action_kind not in (None, "qr"):
        raise StdioSpecError("The probe action_kind must be qr.")
    interval = data.get("interval_seconds", 3.0)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 1.0 <= float(interval) <= 30.0:
        raise StdioSpecError("The probe interval_seconds must be a number from 1 to 30.")
    message_path, expires_path = data.get("message_path"), data.get("expires_path")
    return MCPProbeSpec(
        url=url,
        auth=auth,
        secret_name=secret_name,
        state_path=_dotted(data.get("state_path"), "The probe state_path"),
        states=states,
        message_path=None if message_path is None else _dotted(message_path, "The probe message_path"),
        action_kind=action_kind,
        action_path=None if action_path is None else _dotted(action_path, "The probe action_path"),
        expires_path=None if expires_path is None else _dotted(expires_path, "The probe expires_path"),
        interval_seconds=float(interval),
    )

"""Scan the declared and installed dependency trees for analytics, telemetry, crash-reporting, and ad packages (read-only, offline).

Run: PYTHONPATH=scripts .venv/bin/python -m benchmarks.dependency_analytics_scan
Sources: poetry.lock, pyproject.toml, the active .venv site-packages, client/Package.resolved, web-components/package-lock.json (and package.json files).
A name match is a lead, not proof of data collection; a clean result only covers package names, not hand-written network calls.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.machine import REPO_ROOT  # noqa: E402
from benchmarks.common.results import build_result, write_result  # noqa: E402

# Distinctive vendor or concept names matched as substrings of a package name.
SUBSTRING_TERMS = (
    "sentry", "posthog", "mixpanel", "amplitude", "analytics", "telemetry", "datadog", "newrelic", "bugsnag", "rollbar", "crashlytics",
    "firebase", "appcenter", "plausible", "fullstory", "logrocket", "hotjar", "statsig", "launchdarkly", "opentelemetry", "honeycomb",
    "instabug", "countly", "matomo", "appsflyer", "onesignal", "intercom", "hubspot", "smartlook",
    "langsmith", "langfuse", "logfire", "wandb", "mlflow", "traceloop", "helicone", "arize",
)
# Short names that would false-match as substrings (segments, heapq, adjusted) and are matched only as whole tokens.
TOKEN_TERMS = {"segment", "heap", "otel", "gtag", "adjust", "clarity", "branch"}
PATTERN = re.compile("|".join(SUBSTRING_TERMS + tuple(sorted(TOKEN_TERMS))), re.IGNORECASE)


def matches(name: str) -> bool:
    low = name.lower()
    if any(term in low for term in SUBSTRING_TERMS):
        return True
    return any(token in TOKEN_TERMS for token in re.split(r"[^a-z0-9]+", low))


def poetry_lock_names() -> list[str]:
    path = REPO_ROOT / "poetry.lock"
    if not path.exists():
        return []
    return re.findall(r'^name = "([^"]+)"', path.read_text(), flags=re.MULTILINE)


def site_packages_names() -> list[str]:
    names: list[str] = []
    for site in (REPO_ROOT / ".venv" / "lib").glob("python*/site-packages"):
        for child in site.glob("*.dist-info"):
            names.append(child.name[: -len(".dist-info")].rsplit("-", 1)[0])
    return names


def swift_names() -> list[str]:
    path = REPO_ROOT / "client" / "Package.resolved"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    pins = data.get("pins") or data.get("object", {}).get("pins", [])
    return [p.get("identity") or p.get("package", "") for p in pins]


def npm_names() -> list[str]:
    names: set[str] = set()
    for lock in (REPO_ROOT / "web-components").glob("*/package-lock.json"):
        data = json.loads(lock.read_text())
        for key in data.get("packages", {}):
            if key.startswith("node_modules/"):
                names.add(key.split("node_modules/")[-1])
    for pkg in (REPO_ROOT / "web-components").glob("*/package.json"):
        data = json.loads(pkg.read_text())
        for section in ("dependencies", "devDependencies"):
            names.update((data.get(section) or {}).keys())
    return sorted(names)


def main() -> int:
    sources = {
        "poetry.lock": poetry_lock_names(),
        ".venv site-packages": site_packages_names(),
        "client/Package.resolved": swift_names(),
        "web-components npm": npm_names(),
    }
    runs = []
    total_hits = 0
    for source, names in sources.items():
        hits = sorted({n for n in names if matches(n)})
        total_hits += len(hits)
        runs.append({"source": source, "packages_scanned": len(names), "hits": hits})
        print(f"{source}: scanned {len(names)}, hits {hits}")
    result = build_result(
        "dependency_analytics_scan",
        mode="full",
        subject={"label": "declared-and-installed-dependencies"},
        parameters={"pattern": PATTERN.pattern},
        metrics={"hit_count": {"unit": "packages", "n": 1, "median": total_hits, "min": total_hits, "max": total_hits, "stdev": 0.0}},
        runs=runs,
        notes=[
            "Name-pattern scan only: a clean result does not rule out hand-written network calls, vendored code, or first-party endpoints. The network observation in B9 covers runtime behavior.",
            "A hit is a lead to inspect, not proof of data collection.",
            "Manual follow-up on hits (2026-11-03): opentelemetry-api is required only by fastapi and no opentelemetry SDK or exporter is installed, so its calls are no-ops. langsmith is a transitive dependency of the langchain stack; no Basil code in backend/ or pyproject.toml references LANGSMITH or LANGCHAIN_TRACING settings, and the library traces only when its own environment variables enable it.",
        ],
    )
    print(f"wrote {write_result(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

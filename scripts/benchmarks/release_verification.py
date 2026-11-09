"""Record a download-checksum-attestation verification of a published Basil release (read-only against GitHub).

Run: PYTHONPATH=scripts .venv/bin/python -m benchmarks.release_verification --tag v1.0.1
The DMG is downloaded to ~/.basil-bench/dl and never mounted or launched.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.common.results import build_result, write_result  # noqa: E402

REPO = "stratten/Basil_OS"
DL = Path.home() / ".basil-bench" / "dl"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    DL.mkdir(parents=True, exist_ok=True)

    view = run(["gh", "release", "view", args.tag, "--repo", REPO, "--json", "body,assets"])
    if view.returncode != 0:
        print(view.stderr)
        return 1
    info = json.loads(view.stdout)
    match = re.search(r"/commit/([0-9a-f]{40})", info["body"])
    if not match:
        print("no commit SHA in release notes")
        return 1
    commit = match.group(1)
    dmg_size = next(a["size"] for a in info["assets"] if a["name"] == "Basil.dmg")

    dl = run(["gh", "release", "download", args.tag, "--repo", REPO, "--pattern", "Basil.dmg", "--pattern", "SHA256SUMS.txt", "--clobber"], cwd=DL)
    checksum = run(["shasum", "-a", "256", "-c", "SHA256SUMS.txt"], cwd=DL)
    attest = run(
        [
            "gh", "attestation", "verify", "Basil.dmg", "--repo", REPO,
            "--signer-workflow", f"{REPO}/.github/workflows/validate.yml",
            "--source-ref", "refs/heads/main", "--source-digest", commit,
            "--deny-self-hosted-runners",
        ],
        cwd=DL,
    )
    runs = [
        {"step": "download", "returncode": dl.returncode},
        {"step": "shasum -a 256 -c SHA256SUMS.txt", "returncode": checksum.returncode, "output": checksum.stdout.strip()},
        {"step": "gh attestation verify", "returncode": attest.returncode, "source_digest": commit, "stderr_tail": attest.stderr.strip()[-300:]},
    ]
    ok = all(r["returncode"] == 0 for r in runs)
    result = build_result(
        "release_verification",
        mode="full",
        subject={"label": f"Basil {args.tag}", "commit": commit},
        parameters={"tag": args.tag, "dmg_bytes": dmg_size, "mounted_or_launched": False},
        metrics={"dmg_size": {"unit": "MB", "n": 1, "median": dmg_size / 1e6, "min": dmg_size / 1e6, "max": dmg_size / 1e6, "stdev": 0.0}},
        runs=runs,
        notes=[f"Overall: {'verified' if ok else 'FAILED'}. The DMG was verified by checksum and signed build attestation only; it was not mounted or launched."],
    )
    print(f"wrote {write_result(result)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

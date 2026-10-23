#!/usr/bin/env python3
"""Inspect or explicitly remove the retired local MemVid directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from api.services.maintenance.legacy_memvid_cleanup import cleanup_legacy_memvid_data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="Delete the computed legacy MemVid directory after inspection.",
    )
    args = parser.parse_args()
    report = cleanup_legacy_memvid_data(delete=args.confirm_delete)
    print(json.dumps(report, sort_keys=True))
    return 1 if report["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

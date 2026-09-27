#!/usr/bin/env python3
"""Opt-in production-local validation for durable Mail work-ledger capture.

This is deliberately a manual harness.  It never runs unless the caller
supplies every required environment value, and it only uses the local agent
task API plus read-only SQLite queries for observation.  It does not invoke
Mail directly; the explicitly opted-in root task is responsible for the
bounded metadata query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


LIVE_OPT_IN_ENV = "BASIL_LIVE_WORK_LEDGER_VALIDATION"
DATABASE_ENV = "BASIL_LIVE_KNOWLEDGE_DB_PATH"
EVIDENCE_PATH_ENV = "BASIL_LIVE_WORK_LEDGER_EVIDENCE_PATH"
DATE_FROM_ENV = "BASIL_LIVE_WORK_LEDGER_DATE_FROM"
DATE_TO_ENV = "BASIL_LIVE_WORK_LEDGER_DATE_TO"
MAILBOX_ENV = "BASIL_LIVE_WORK_LEDGER_MAILBOX"
PORT_FILE = Path(__file__).resolve().parents[5] / ".server_port"
TERMINAL_TASK_STATES = frozenset({"completed", "failed", "cancelled"})
MANIFEST_STATES = frozenset(
    {
        "submitted",
        "awaiting_manual_restart",
        "restart_observed",
        "completed",
        "failed",
        "cancelled",
    }
)


@dataclass(frozen=True)
class ValidationConfiguration:
    database_path: Path
    evidence_path: Path
    mailbox: str
    date_from: str
    date_to: str
    port: int


def _require_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _validate_iso_date(name: str, value: str) -> str:
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 date or datetime.") from exc


def discover_current_server_port(port_file: Path = PORT_FILE) -> int:
    """Read the exact current development-server port; never guess a fallback."""
    try:
        port = int(port_file.read_text(encoding="utf-8").strip())
    except FileNotFoundError as exc:
        raise ValueError(f"Current server port file is missing: {port_file}") from exc
    except ValueError as exc:
        raise ValueError(f"Current server port file is invalid: {port_file}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Current server port is outside the valid range: {port}")
    return port


def load_configuration() -> ValidationConfiguration:
    """Load explicit local-only configuration and fail before any API call."""
    if os.environ.get(LIVE_OPT_IN_ENV) != "1":
        raise ValueError(f"{LIVE_OPT_IN_ENV}=1 is required before this harness can run.")

    database_path = Path(_require_environment(DATABASE_ENV)).expanduser()
    if not database_path.is_file():
        raise ValueError(f"Knowledge database does not exist: {database_path}")
    evidence_path = Path(_require_environment(EVIDENCE_PATH_ENV)).expanduser()
    mailbox = _require_environment(MAILBOX_ENV)
    date_from = _validate_iso_date(DATE_FROM_ENV, _require_environment(DATE_FROM_ENV))
    date_to = _validate_iso_date(DATE_TO_ENV, _require_environment(DATE_TO_ENV))
    if date_from > date_to:
        raise ValueError(f"{DATE_FROM_ENV} must be no later than {DATE_TO_ENV}.")
    return ValidationConfiguration(
        database_path=database_path,
        evidence_path=evidence_path,
        mailbox=mailbox,
        date_from=date_from,
        date_to=date_to,
        port=discover_current_server_port(),
    )


def build_read_only_mail_prompt(mailbox: str, date_from: str, date_to: str) -> str:
    """Construct the only root-task instruction this harness can submit."""
    return (
        "Use only email_service.get_email_metadata to perform a bounded, read-only "
        f"Mail mailbox {mailbox!r} metadata query from {date_from} through {date_to}. "
        "Do not use get_emails or expand_email_details. Do not compose, draft, send, "
        "reply, forward, move, delete, flag, mark read, archive, or otherwise modify "
        "Mail. Return only a concise count and the coverage metadata."
    )


def generated_mail_script_evidence(
    mailbox: str,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """Record the exact bounded script shape without executing AppleScript."""
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.email_models import (
        EmailSearchCriteria,
    )
    from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.mail_app_service import (
        MailAppService,
    )

    script = MailAppService().get_email_metadata_script(
        mailbox,
        1,
        EmailSearchCriteria(
            date_from=datetime.fromisoformat(date_from),
            date_to=datetime.fromisoformat(date_to),
        ),
    )
    return {
        "sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "input": {
            "folder": mailbox,
            "limit": 1,
            "date_from": date_from,
            "date_to": date_to,
        },
        "contract": {
            "metadata_only": "content of aMessage" not in script,
            "date_bounded": "(date received of aMessage) >= date" in script and "(date received of aMessage) <= date" in script,
            "no_mail_write_tokens": all(
                token not in script.lower()
                for token in ("make new outgoing message", "\nsend ", "\ndelete ", "\nmove ")
            ),
        },
    }


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def read_ledger_evidence(database_path: Path, root_task_id: str) -> dict[str, Any]:
    """Read the root's ledger and receipts without creating or updating anything."""
    with _connect_read_only(database_path) as connection:
        sessions = connection.execute(
            """
            SELECT id, root_task_id, scope_json, status, created_at, updated_at
            FROM agent_work_sessions
            WHERE root_task_id = ?
            ORDER BY created_at ASC
            """,
            (root_task_id,),
        ).fetchall()
        receipts = connection.execute(
            """
            SELECT id, session_id, agent_task_id, service, method, receipt_key,
                   requested_effect_json, execution_state, verification_status,
                   evidence_json, discrepancy_json, created_at
            FROM agent_work_receipts
            WHERE agent_task_id = ?
            ORDER BY created_at ASC
            """,
            (root_task_id,),
        ).fetchall()
        items = connection.execute(
            """
            SELECT agent_work_items.id, agent_work_items.session_id,
                   agent_work_items.external_id
            FROM agent_work_items
            INNER JOIN agent_work_sessions
                    ON agent_work_sessions.id = agent_work_items.session_id
            WHERE agent_work_sessions.root_task_id = ?
            ORDER BY agent_work_items.created_at ASC
            """,
            (root_task_id,),
        ).fetchall()

    def decode(value: str | None) -> Any:
        return json.loads(value) if value else {}

    return {
        "session_count": len(sessions),
        "sessions": [
            {
                **dict(row),
                "scope": decode(row["scope_json"]),
            }
            for row in sessions
        ],
        "receipt_count": len(receipts),
        "item_count": len(items),
        "items": [dict(row) for row in items],
        "receipts": [
            {
                **dict(row),
                "requested_effect": decode(row["requested_effect_json"]),
                "evidence": decode(row["evidence_json"]),
                "discrepancy": decode(row["discrepancy_json"]),
            }
            for row in receipts
        ],
    }


def validate_capture_evidence(ledger: dict[str, Any], root_task_id: str) -> dict[str, Any]:
    """Require observable bounded-read capture; zero receipts never pass."""
    matching_receipts = [
        receipt
        for receipt in ledger["receipts"]
        if receipt["agent_task_id"] == root_task_id
        and receipt["service"] == "email_service"
        and receipt["method"] == "get_email_metadata"
        and receipt["requested_effect"].get("material_write") is False
    ]
    coverage = []
    for session in ledger["sessions"]:
        session_coverage = session["scope"].get("coverage")
        if isinstance(session_coverage, dict):
            coverage.append(session_coverage)
    for receipt in matching_receipts:
        result = receipt["evidence"].get("result")
        if isinstance(result, dict):
            result_coverage = result.get("coverage_metadata")
            if isinstance(result_coverage, dict):
                coverage.append(result_coverage)

    if not matching_receipts:
        raise RuntimeError(
            "No observable read-only email metadata receipt exists for the submitted root task."
        )
    if len(matching_receipts) != 1:
        raise RuntimeError(
            "Expected exactly one email metadata receipt for the submitted root invocation."
        )
    receipt_keys = [receipt["receipt_key"] for receipt in matching_receipts]
    if len(receipt_keys) != len(set(receipt_keys)):
        raise RuntimeError("Duplicate email metadata receipt key exists for the submitted root task.")
    if not coverage:
        raise RuntimeError("No coverage metadata was captured in the work ledger evidence.")
    item_count = int(ledger.get("item_count", 0))
    if item_count < 1:
        raise RuntimeError("No durable email items were captured for the submitted root task.")
    return {
        "matching_receipt_count": len(matching_receipts),
        "output_coverage": coverage,
        "item_count": item_count,
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Evidence manifest is missing: {path}") from exc
    if manifest.get("state") not in MANIFEST_STATES:
        raise ValueError("Evidence manifest has no recognized deterministic state.")
    if not manifest.get("root_task_id"):
        raise ValueError("Evidence manifest has no root task id.")
    return manifest


def _request_status(client: httpx.Client, base_url: str, root_task_id: str) -> dict[str, Any]:
    response = client.get(f"{base_url}/api/v1/agent-tasks/{root_task_id}")
    response.raise_for_status()
    return response.json()


def submit(configuration: ValidationConfiguration) -> dict[str, Any]:
    """Submit exactly one user-visible root task after all fail-closed checks."""
    if configuration.evidence_path.exists():
        raise ValueError(
            f"Evidence manifest already exists: {configuration.evidence_path}. "
            "Use observe or resume; submit never creates a replacement ledger."
        )

    root_task_id = str(uuid.uuid4())
    before = read_ledger_evidence(configuration.database_path, root_task_id)
    if before["session_count"] or before["receipt_count"]:
        raise RuntimeError("New root task id unexpectedly already has ledger evidence.")
    base_url = f"http://127.0.0.1:{configuration.port}"
    prompt = build_read_only_mail_prompt(
        configuration.mailbox,
        configuration.date_from,
        configuration.date_to,
    )
    manifest = {
        "state": "submitted",
        "root_task_id": root_task_id,
        "base_url": base_url,
        "submitted_at": datetime.now().astimezone().isoformat(),
        "mailbox": configuration.mailbox,
        "date_bounds": {"from": configuration.date_from, "to": configuration.date_to},
        "prompt": prompt,
        "generated_mail_script": generated_mail_script_evidence(
            configuration.mailbox,
            configuration.date_from,
            configuration.date_to,
        ),
        "before": before,
    }
    _write_manifest(configuration.evidence_path, manifest)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base_url}/api/v1/agent-tasks/process",
                json={"agent_task": prompt, "agent_task_id": root_task_id},
            )
            response.raise_for_status()
            manifest["submission_response"] = response.json()
    except Exception:
        manifest["state"] = "awaiting_manual_restart"
        manifest["submission_error"] = "Submission did not complete; inspect the local task API before retrying."
        _write_manifest(configuration.evidence_path, manifest)
        raise

    _write_manifest(configuration.evidence_path, manifest)
    return manifest


def observe(configuration: ValidationConfiguration, *, require_restart: bool) -> dict[str, Any]:
    """Observe a submitted root without posting a task or issuing a Mail query."""
    manifest = _read_manifest(configuration.evidence_path)
    root_task_id = manifest["root_task_id"]
    base_url = f"http://127.0.0.1:{configuration.port}"

    with httpx.Client(timeout=30.0) as client:
        task = _request_status(client, base_url, root_task_id)
    ledger = read_ledger_evidence(configuration.database_path, root_task_id)
    manifest["last_observed_at"] = datetime.now().astimezone().isoformat()
    manifest["last_observed_base_url"] = base_url
    manifest["task"] = task
    manifest["ledger"] = ledger

    task_status = task.get("status", "")
    if require_restart:
        if manifest["state"] not in {"submitted", "awaiting_manual_restart"}:
            raise ValueError("Manual restart can only be recorded before a restart observation.")
        capture_validation = validate_capture_evidence(ledger, root_task_id)
        repeated_ledger = read_ledger_evidence(configuration.database_path, root_task_id)
        repeated_validation = validate_capture_evidence(repeated_ledger, root_task_id)
        if (
            capture_validation["item_count"] != repeated_validation["item_count"]
            or ledger["items"] != repeated_ledger["items"]
        ):
            raise RuntimeError(
                "Durable item count changed during the root audit; refusing restart checkpoint."
            )
        manifest["capture_validation"] = {
            **capture_validation,
            "stable_item_count": True,
        }
        manifest["state"] = "awaiting_manual_restart"
        manifest["manual_restart_instruction"] = (
            "Restart the backend manually, then run this harness with --phase resume. "
            "No new root task or ledger will be created."
        )
    elif manifest["state"] == "awaiting_manual_restart":
        if ledger["session_count"] != 1:
            raise RuntimeError(
                "Expected exactly one durable ledger session after restart; refusing to accept a replacement ledger."
            )
        manifest["state"] = "restart_observed"
    elif task_status in TERMINAL_TASK_STATES:
        manifest["state"] = task_status

    if manifest["state"] in {"restart_observed", "completed"}:
        manifest["capture_validation"] = validate_capture_evidence(ledger, root_task_id)

    _write_manifest(configuration.evidence_path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("submit", "observe", "pause-for-restart", "resume"))
    args = parser.parse_args(argv)
    try:
        configuration = load_configuration()
        if args.phase == "submit":
            manifest = submit(configuration)
        else:
            manifest = observe(
                configuration,
                require_restart=args.phase == "pause-for-restart",
            )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        print(f"LIVE WORK LEDGER VALIDATION FAILED CLOSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

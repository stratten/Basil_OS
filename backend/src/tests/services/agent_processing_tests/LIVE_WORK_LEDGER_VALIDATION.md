# Live Phase 1–3 Work-Ledger Validation

`live_work_ledger_validation.py` is an opt-in, production-local validation
harness for the durable work ledger. It is intentionally not a pytest test and
does not run from CI.

## Safety boundary

The harness fails before making an HTTP request unless all of the following are
present:

```bash
export BASIL_LIVE_WORK_LEDGER_VALIDATION=1
export BASIL_LIVE_KNOWLEDGE_DB_PATH="$HOME/.basil/knowledge_base.db"
export BASIL_LIVE_WORK_LEDGER_EVIDENCE_PATH="$PWD/live-work-ledger-evidence.json"
export BASIL_LIVE_WORK_LEDGER_DATE_FROM="2026-07-01T00:00:00"
export BASIL_LIVE_WORK_LEDGER_DATE_TO="2026-07-02T00:00:00"
```

It reads the active port only from the current repository `.server_port` and
does not fall back to port 8000. The only submitted root task is a fixed,
date-bounded `email_service.get_email_metadata` request. Its instruction
forbids content expansion and every Mail mutation, including draft, send,
reply, move, delete, archive, flag, and read-state changes.

The harness itself never invokes `osascript`, never queries Mail, and never
writes to the knowledge database. It queries the durable ledger through a
SQLite `mode=ro` connection with `PRAGMA query_only=ON`. The only local file it
writes is the caller-selected evidence manifest.

## Runbook

From `Basil/`, start with a new evidence path:

```bash
poetry run python src/tests/services/agent_processing_tests/live_work_ledger_validation.py submit
poetry run python src/tests/services/agent_processing_tests/live_work_ledger_validation.py observe
```

To validate manual backend restart continuity, do not submit a second task:

```bash
poetry run python src/tests/services/agent_processing_tests/live_work_ledger_validation.py pause-for-restart
# Restart the backend manually.
poetry run python src/tests/services/agent_processing_tests/live_work_ledger_validation.py resume
```

`submit` refuses to run when an evidence manifest already exists.
`pause-for-restart` first verifies the submitted root has an observable email
receipt, coverage metadata, and at least one durable item, then performs a
second read-only ledger snapshot to require a stable item count and identity
set. It will not permit a restart checkpoint for an empty or changing ledger.
`resume` performs only task-status and ledger reads, re-reads the current
`.server_port` after restart, and fails unless exactly one ledger session
exists for the original root task. It cannot silently create a replacement
root task or ledger.

## Required evidence and acceptance

The JSON manifest records:

- fixed root task ID, prompt, submission response, and local API base URL;
- date bounds and the generated metadata-script SHA-256;
- script input (`folder`, `limit`, and both dates) and static safety contract;
- read-only ledger session rows, receipt rows, requested effects, receipt
  evidence, discrepancies, and captured coverage metadata;
- task status before/after the manual restart state transition.

Successful live validation requires a receipt whose `agent_task_id` is the
manifest root task, `service` is `email_service`, and `method` is
`get_email_metadata`. It must have `requested_effect.material_write == false`
and coverage in the session scope and/or receipt evidence. It also requires a
non-zero durable item count before the restart checkpoint, with item metadata
excluding email body/content fields. A zero-receipt or zero-item result is a
failed validation, not evidence of success: it means that the capture path was
not observable for the submitted root task.

This validation exercises the task API, work-ledger, and Mail metadata contract independently of unrelated setup or delegation features.

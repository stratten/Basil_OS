"""Opt-in, read-only live probe for Mail.app metadata retrieval.

Run only with an explicit mailbox selection:
    BASIL_RUN_MAIL_READONLY_PROBE=1 BASIL_MAIL_PROBE_FOLDER=Inbox \
      poetry run python scripts/probe_mail_metadata_readonly.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.parsing import (
    MailAppParser,
)
from api.services.agent_processing.tools.direct_application_interactions.email_integration.mail_app.script_generators import (
    MailAppScriptGenerator,
)

_OPT_IN_ENVIRONMENT = "BASIL_RUN_MAIL_READONLY_PROBE"
_MAILBOX_ENVIRONMENT = "BASIL_MAIL_PROBE_FOLDER"


async def _run_probe(folder: str) -> int:
    script = MailAppScriptGenerator().get_email_metadata_script(folder=folder, limit=1)
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        print(f"Mail read-only probe failed: {stderr.decode().strip()}", file=sys.stderr)
        return process.returncode or 1

    emails = MailAppParser().parse_emails_from_applescript(stdout.decode(), "Mail")
    coverage = getattr(emails, "coverage_metadata", {})
    print(
        "Mail read-only probe passed: "
        f"folder={folder!r}, returned={len(emails)}, coverage={coverage}"
    )
    return 0


def main() -> int:
    if os.environ.get(_OPT_IN_ENVIRONMENT) != "1":
        print(
            f"SKIPPED: set {_OPT_IN_ENVIRONMENT}=1 to opt in to Mail.app access."
        )
        return 0

    folder = os.environ.get(_MAILBOX_ENVIRONMENT, "").strip()
    if not folder:
        print(
            f"SKIPPED: set {_MAILBOX_ENVIRONMENT} to the mailbox to inspect."
        )
        return 0

    return asyncio.run(_run_probe(folder))


if __name__ == "__main__":
    raise SystemExit(main())

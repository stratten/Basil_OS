"""Turn a setup-agent failure into the payload of an error stream event."""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.core.models.reasoning.local_model_failure import failure_payload, find_local_model_failure


def setup_error_payload(error: BaseException, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Error-event payload for a failed setup-agent turn.

    A failed local-model decode is described in plain language with its recovery actions under ``local_model_failure``, so the UI can offer them instead of a raw native message.
    Any other failure keeps the original behavior of reporting its text.
    """

    failure = find_local_model_failure(error)
    if failure is None:
        return {"message": str(error), "run_id": run_id}
    description = failure_payload(failure)
    return {"message": description["message"], "run_id": run_id, "local_model_failure": description}

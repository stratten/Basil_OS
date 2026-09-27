"""Non-invasive durable-ledger capture for normalized service results."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_ledger_capture import (
    ToolLedgerCaptureCoordinator,
)
if TYPE_CHECKING:
    from api.services.agent_processing.service_capabilities.service_execution_engine import (
        ExecutionResult,
    )


async def capture_normalized_service_result(
    result: "ExecutionResult",
    parameters: Optional[dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """Persist a receipt without allowing persistence faults to alter execution."""
    try:
        await ToolLedgerCaptureCoordinator().capture_raw_service(
            service=result.service or "",
            method=result.method or "",
            parameters=parameters,
            result=result,
        )
    except Exception as capture_error:  # pragma: no cover - defensive isolation
        logger.warning(
            "Work-ledger engine capture failed service=%s method=%s error_type=%s: %s",
            result.service,
            result.method,
            type(capture_error).__name__,
            capture_error,
        )

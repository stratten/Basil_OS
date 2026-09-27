"""Shared execution-limit constants for the LangChain agent executor.

Centralizes the wall-clock cap and LangChain's generic force-stop string so the
executor configuration (``agent_executor_factory``) and the user-facing
relabeling of that string (``agent_execution_core``) cannot drift apart.
"""

from __future__ import annotations

# Wall-clock ceiling handed to ``AgentExecutor(max_execution_time=...)``.
# LangChain's async ``_acall`` wraps the reasoning loop in
# ``async with asyncio_timeout(self.max_execution_time)``, so this cap CAN
# interrupt a mid-tool-call ``await`` (verified against langchain 0.3.27). With
# ``max_iterations=None`` (uncapped), this timeout is the ONLY reason LangChain
# emits its force-stop message.
AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS = 1200

# The exact constant string LangChain's
# ``BaseSingleActionAgent.return_stopped_response("force")`` emits on a forced
# stop. Because iterations are uncapped, this string can ONLY mean the
# wall-clock timeout above — never an iteration limit.
LANGCHAIN_FORCE_STOP_SENTINEL = "Agent stopped due to iteration limit or time limit."


def execution_timeout_message() -> str:
    """User-facing replacement for LangChain's ambiguous force-stop string."""
    minutes = int(AGENT_EXECUTOR_MAX_EXECUTION_TIME_SECONDS // 60)
    return (
        f"Basil stopped this task after reaching its {minutes}-minute "
        "execution time limit."
    )

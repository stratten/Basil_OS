"""Routes that let the user answer a prompt shown by a running shell command."""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.agent_processing.tools.direct_application_interactions.shell.command_input_broker import (
    MAX_COMMAND_INPUT_CHARS,
    CommandInputBroker,
    CommandInputConflictError,
    CommandInputNotFoundError,
)

router = APIRouter()


class CommandInputResponseRequest(BaseModel):
    action: Literal["answer", "cancel"]
    value: Optional[str] = Field(default=None, max_length=MAX_COMMAND_INPUT_CHARS + 2)
    agent_task_id: Optional[str] = None


@router.get("/{agent_task_id}/command-input/pending")
async def list_pending_command_inputs(agent_task_id: str):
    return {"requests": CommandInputBroker.pending_for_task(agent_task_id)}


@router.post("/command-input/{request_id}/respond")
async def respond_to_command_input(request_id: str, request: CommandInputResponseRequest):
    try:
        CommandInputBroker.respond(
            request_id,
            action=request.action,
            value=request.value,
            agent_task_id=request.agent_task_id,
        )
    except CommandInputNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CommandInputConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "success": True,
        "message": "Input sent" if request.action == "answer" else "Input request canceled",
    }

"""Interaction style choices made on the last setup preferences step."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.setup_assistant.interaction_preferences_store import save_interaction_preferences
from api.services.setup_assistant.interaction_style_catalog import (
    INTERACTION_STYLE_GROUPS,
    MAX_SELECTED_OPTIONS,
    resolve_interaction_style,
)

router = APIRouter(prefix="/interaction-style", tags=["Setup Assistant"])


class InteractionStyleOptionResponse(BaseModel):
    id: str
    label: str


class InteractionStyleGroupResponse(BaseModel):
    id: str
    title: str
    multiple: bool
    options: List[InteractionStyleOptionResponse]


class InteractionStyleCatalogResponse(BaseModel):
    groups: List[InteractionStyleGroupResponse]


class InteractionStyleSaveRequest(BaseModel):
    selections: Dict[str, List[str]] = Field(default_factory=dict, max_length=MAX_SELECTED_OPTIONS)


class InteractionStyleSaveResponse(BaseModel):
    saved: bool
    instructions: List[str]


@router.get("", response_model=InteractionStyleCatalogResponse)
async def get_interaction_style_catalog() -> InteractionStyleCatalogResponse:
    """The statements the setup UI offers, grouped by what they decide."""

    return InteractionStyleCatalogResponse(
        groups=[
            InteractionStyleGroupResponse(
                id=group.id,
                title=group.title,
                multiple=group.multiple,
                options=[InteractionStyleOptionResponse(id=option.id, label=option.label) for option in group.options],
            )
            for group in INTERACTION_STYLE_GROUPS
        ]
    )


@router.post("", response_model=InteractionStyleSaveResponse)
async def save_interaction_style(request: InteractionStyleSaveRequest) -> InteractionStyleSaveResponse:
    """Save the chosen statements as the profile's interaction preferences.

    An empty choice saves nothing, so a skipped step never overwrites preferences the user already has.
    """
    try:
        instructions = resolve_interaction_style(request.selections)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not instructions:
        return InteractionStyleSaveResponse(saved=False, instructions=[])
    try:
        await save_interaction_preferences("\n".join(f"- {instruction}" for instruction in instructions))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return InteractionStyleSaveResponse(saved=True, instructions=instructions)

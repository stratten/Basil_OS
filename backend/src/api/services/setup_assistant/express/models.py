"""Wire models shared by the express planner, applier, receipt and routes."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ComfortLevel = Literal["cautious", "balanced", "all_in"]
ItemGroup = Literal["downloads", "learning", "background", "hotkeys"]
ItemOutcome = Literal["started", "applied", "skipped", "failed"]
ReceiptState = Literal["on", "partial", "off"]


class DeviceSummary(BaseModel):
    total_ram_gb: int
    memory_tier: str
    chip_label: Optional[str] = None
    is_apple_silicon: bool
    free_disk_gb: Optional[float] = None
    summary: str


class PreflightCheck(BaseModel):
    id: Literal["disk", "network"]
    ok: bool
    message: str


class ExpressItem(BaseModel):
    id: str
    group: ItemGroup
    title: str
    summary: str
    caution: Optional[str] = None
    comfort: ComfortLevel
    stays_on_this_mac: bool = True
    permissions: List[str] = Field(default_factory=list)
    model_id: Optional[str] = None
    model_name: Optional[str] = None
    download_size_gb: Optional[float] = None
    native: bool = False
    already_done: bool = False
    unavailable_reason: Optional[str] = None
    selected: bool
    # Whether the review screen starts this item ticked. An item with `selected` true and `default_ticked` false is offered unticked and runs only if the person ticks it.
    default_ticked: bool = True


class ExpressPlan(BaseModel):
    comfort: ComfortLevel
    device: DeviceSummary
    preflight: List[PreflightCheck]
    items: List[ExpressItem]
    notes: List[str]
    thinking_model_available: bool


class ExpressApplyRequest(BaseModel):
    comfort: ComfortLevel
    selected_item_ids: List[str]


class ExpressItemResult(BaseModel):
    id: str
    outcome: ItemOutcome
    message: str


class ExpressApplyResult(BaseModel):
    comfort: ComfortLevel
    results: List[ExpressItemResult]
    thinking_model_id: Optional[str] = None


class ReceiptItem(BaseModel):
    id: str
    group: ItemGroup
    title: str
    state: ReceiptState
    detail: str
    where_to_change: str


class SetupReceipt(BaseModel):
    items: List[ReceiptItem]

"""Builds the express plan: what each comfort level would do on this particular Mac."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from api.core.models.model_download.disk_space import (
    disk_shortfall_message,
    download_disk_required_gb,
    parse_registry_size_gb,
)

from .catalog import (
    CATALOG,
    DOWNLOAD_THINKING,
    DOWNLOAD_VOICE_FAST,
    DOWNLOAD_VOICE_QUALITY,
    ENTRY_BY_ID,
    already_matches,
    caution_for,
    includes,
    summary_for,
)
from .device import can_reach_download_host, read_device_summary
from .models import ComfortLevel, DeviceSummary, ExpressItem, ExpressPlan, PreflightCheck

# The starter pack numbers its models by download priority: 1 and 2 are the two transcription models, 3 is the reasoning model.
_STARTER_ID_BY_PRIORITY: Dict[int, str] = {1: DOWNLOAD_VOICE_FAST, 2: DOWNLOAD_VOICE_QUALITY, 3: DOWNLOAD_THINKING}

# Disk is allocated in this order, so a tight disk never gives the thinking model's room to a voice model.
_DISK_ORDER = (DOWNLOAD_THINKING, DOWNLOAD_VOICE_FAST, DOWNLOAD_VOICE_QUALITY)

_DESCRIPTION_SIZE = re.compile(r"\((\d+(?:\.\d+)?)\s*(MB|GB)\)", re.IGNORECASE)

NETWORK_MESSAGE = "I couldn't reach the download server. Check your internet connection and check again."

LOCAL_NOTE = "Everything here stays on this Mac while I think with the local model. If you later switch to a cloud model, the text I read goes to that provider."
LOW_MEMORY_NOTE = "This Mac has less memory than most, so I picked a smaller thinking model. It works, but answers will be slower than on a larger Mac."
NO_THINKING_NOTE = "I can't set up the thinking model right now. You can finish that step yourself on the next screen."


@dataclass
class ExpressEnvironment:
    """Everything the planner reads from the outside, so tests can supply fakes."""

    read_device: Callable[[], DeviceSummary]
    starter_models: Callable[[], List[Dict[str, Any]]]
    is_installed: Callable[[str, str], bool]
    model_info: Callable[[str], Optional[Dict[str, Any]]]
    can_reach_download_host: Callable[[], Awaitable[bool]]
    load_preferences: Callable[[], Any]


def default_environment(model_service: Any) -> ExpressEnvironment:
    from api.core.models.models_registry import get_model
    from api.core.preferences.preferences_io import load_preferences
    from api.routes.onboarding import get_starter_models

    return ExpressEnvironment(
        read_device=read_device_summary,
        starter_models=lambda: get_starter_models(model_service),
        is_installed=model_service.is_model_downloaded,
        model_info=get_model,
        can_reach_download_host=can_reach_download_host,
        load_preferences=load_preferences,
    )


@dataclass
class DownloadSpec:
    model_type: str
    variant: str
    model_id: str
    display_name: Optional[str]
    size_gb: Optional[float]
    installed: bool


def _size_from_description(description: str) -> Optional[float]:
    match = _DESCRIPTION_SIZE.search(description)
    if match is None:
        return None
    value = float(match.group(1))
    return value / 1024 if match.group(2).upper() == "MB" else value


class ExpressPlanner:
    def __init__(self, environment: ExpressEnvironment) -> None:
        self._environment = environment

    def download_specs(self) -> Dict[str, DownloadSpec]:
        """The three starter downloads keyed by catalog id, read once from the starter pack for this Mac."""
        env = self._environment
        specs: Dict[str, DownloadSpec] = {}
        for starter in env.starter_models():
            entry_id = _STARTER_ID_BY_PRIORITY.get(int(starter.get("priority", 0)))
            if entry_id is None:
                continue
            model_type = str(starter["model_type"])
            variant = str(starter["variant"])
            model_id = f"{model_type}-{variant}"
            info = env.model_info(model_id) or {}
            size_gb = parse_registry_size_gb(info.get("size"))
            if size_gb is None:
                size_gb = _size_from_description(str(starter.get("description", "")))
            specs[entry_id] = DownloadSpec(
                model_type=model_type,
                variant=variant,
                model_id=model_id,
                display_name=str(info.get("display_name") or "") or None,
                size_gb=size_gb,
                installed=bool(env.is_installed(model_type, variant)),
            )
        return specs

    async def build_plan(self, comfort: ComfortLevel) -> ExpressPlan:
        env = self._environment
        device = env.read_device()
        preferences = env.load_preferences()
        specs = self.download_specs()

        unavailable: Dict[str, str] = {}
        remaining_gb = device.free_disk_gb
        for entry_id in _DISK_ORDER:
            spec = specs.get(entry_id)
            if spec is None or spec.installed or spec.size_gb is None:
                continue
            required_gb = download_disk_required_gb(f"{spec.size_gb}GB")
            if remaining_gb is None or required_gb is None:
                continue
            if remaining_gb < required_gb:
                unavailable[entry_id] = disk_shortfall_message(
                    spec.display_name or ENTRY_BY_ID[entry_id].title, required_gb, remaining_gb
                )
            else:
                remaining_gb -= spec.size_gb

        needs_download = any(not spec.installed for spec in specs.values())
        if not needs_download:
            disk_check = PreflightCheck(id="disk", ok=True, message="Nothing needs downloading.")
        elif unavailable:
            disk_check = PreflightCheck(id="disk", ok=False, message="This Mac does not have enough free space for every download.")
        elif device.free_disk_gb is None:
            disk_check = PreflightCheck(
                id="disk", ok=True, message="I couldn't read the free disk space, so each download checks for room as it starts."
            )
        else:
            disk_check = PreflightCheck(id="disk", ok=True, message="There is room for the downloads.")

        pending = [entry_id for entry_id in _DISK_ORDER if entry_id in specs and not specs[entry_id].installed and entry_id not in unavailable]
        if not pending:
            network_check = PreflightCheck(id="network", ok=True, message="No downloads are waiting, so no internet connection is needed.")
        elif await env.can_reach_download_host():
            network_check = PreflightCheck(id="network", ok=True, message="The download server is reachable.")
        else:
            for entry_id in pending:
                unavailable[entry_id] = NETWORK_MESSAGE
            network_check = PreflightCheck(id="network", ok=False, message=NETWORK_MESSAGE)

        items: List[ExpressItem] = []
        for entry in CATALOG:
            if not includes(comfort, entry):
                continue
            extra: Dict[str, Any] = {}
            if entry.group == "downloads":
                spec = specs.get(entry.id)
                if spec is None:
                    continue
                already = spec.installed
                reason = None if already else unavailable.get(entry.id)
                extra = {"model_id": spec.model_id, "model_name": spec.display_name, "download_size_gb": spec.size_gb}
            else:
                already = already_matches(entry.id, comfort, preferences)
                reason = None
            items.append(
                ExpressItem(
                    id=entry.id,
                    group=entry.group,
                    title=entry.title,
                    summary=summary_for(entry.id, comfort),
                    caution=caution_for(entry.id),
                    comfort=entry.comfort,
                    permissions=list(entry.permissions),
                    native=entry.native,
                    already_done=already,
                    unavailable_reason=reason,
                    selected=reason is None and not already,
                    **extra,
                )
            )

        thinking = next((item for item in items if item.id == DOWNLOAD_THINKING), None)
        thinking_available = thinking is not None and (thinking.already_done or thinking.selected)

        notes = [LOCAL_NOTE]
        if device.memory_tier == "low":
            notes.append(LOW_MEMORY_NOTE)
        if not thinking_available:
            notes.append(NO_THINKING_NOTE)

        return ExpressPlan(
            comfort=comfort,
            device=device,
            preflight=[disk_check, network_check],
            items=items,
            notes=notes,
            thinking_model_available=thinking_available,
        )

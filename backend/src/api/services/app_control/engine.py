"""Applies, reads, and undoes agent-requested setting changes under the tier rules."""

from __future__ import annotations

import logging
import math
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

from api.core.preferences import preferences_io

from .apply_hooks import default_apply_hooks
from .approval import SettingsChangeApprovalManager, SettingsChangeApprovalRequest, get_settings_change_approval_manager
from .entries import APPEARANCE_GROUP, get_default_registry
from .journal import ChangeJournal, get_default_journal
from .manifest import APPROVAL_TIERS, ControlEntry, ControlRegistry, Tier

logger = logging.getLogger(__name__)

MAX_CHANGES_PER_CALL = 12
LIST_LIMIT = 40
RATE_LIMIT_CHANGES = 30
RATE_LIMIT_WINDOW_SECONDS = 600.0

Publisher = Callable[[Any], Awaitable[None]]
ChangeNotifier = Callable[[List[str]], Awaitable[Any]]


async def notify_settings_changed(keys: List[str]) -> None:
    from api.services.settings_changed_broadcast import broadcast_settings_changed

    await broadcast_settings_changed(keys)


async def publish_appearance(preferences: Any) -> None:
    """Send the complete appearance snapshot to connected clients, built through the same model the Settings route uses."""
    from api.routes.settings_routes.appearance_routes import AppearanceSettings
    from api.services.appearance_broadcast import broadcast_appearance_update

    snapshot = AppearanceSettings.model_validate(
        {name: getattr(preferences.ui, name) for name in AppearanceSettings.model_fields}
    )
    await broadcast_appearance_update(snapshot.model_dump())


DEFAULT_PUBLISHERS: Dict[str, Publisher] = {APPEARANCE_GROUP: publish_appearance, **default_apply_hooks()}


def _same(first: Any, second: Any) -> bool:
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
        return len(first) == len(second) and all(_same(a, b) for a, b in zip(first, second))
    if isinstance(first, (int, float)) and isinstance(second, (int, float)) and not isinstance(first, bool) and not isinstance(second, bool):
        return math.isclose(float(first), float(second), rel_tol=0.0, abs_tol=1e-9)
    return first == second


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **extra}


class AppControlEngine:
    """The one place an agent's settings request is validated, approved, applied, published, and journaled."""

    def __init__(
        self,
        *,
        registry: Optional[ControlRegistry] = None,
        journal: Optional[ChangeJournal] = None,
        approval_manager: Optional[SettingsChangeApprovalManager] = None,
        publishers: Optional[Mapping[str, Publisher]] = None,
        change_notifier: Optional[ChangeNotifier] = notify_settings_changed,
    ) -> None:
        self._registry = registry or get_default_registry()
        self._journal = journal or get_default_journal()
        self._approvals = approval_manager or get_settings_change_approval_manager()
        self._publishers = dict(DEFAULT_PUBLISHERS if publishers is None else publishers)
        self._change_notifier = change_notifier

    @property
    def registry(self) -> ControlRegistry:
        return self._registry

    @property
    def journal(self) -> ChangeJournal:
        return self._journal

    def describe(self, entry: ControlEntry, preferences: Any) -> Dict[str, Any]:
        """What an agent is told about one entry. A human-only entry never reveals a value."""
        described: Dict[str, Any] = {
            "key": entry.key,
            "label": entry.label,
            "description": entry.description,
            "tier": entry.tier.value,
            "changeable": entry.changeable,
            "where_in_settings": entry.where_in_settings,
        }
        if entry.allowed:
            described["allowed"] = list(entry.allowed)
        if entry.kind == "color":
            described["format"] = "hex color such as #FF69B4"
        if entry.tier != Tier.HUMAN_ONLY and entry.read is not None:
            described["current"] = entry.render(entry.read(preferences))
        if entry.tier in APPROVAL_TIERS:
            described["needs_approval"] = True
        return described

    def list_entries(self, query: str = "", limit: int = LIST_LIMIT) -> Dict[str, Any]:
        """Settings an agent can see. With no query only changeable settings are listed; a query also finds the ones only the user can change."""
        preferences = preferences_io.load_preferences()
        query = (query or "").strip()
        entries = self._registry.search(query)
        if not query:
            entries = [entry for entry in entries if entry.changeable]
        shown = entries[: max(1, limit)]
        result: Dict[str, Any] = {
            "ok": True,
            "count": len(entries),
            "settings": [self.describe(entry, preferences) for entry in shown],
        }
        if len(shown) < len(entries):
            result["truncated"] = True
            result["note"] = f"Showing {len(shown)} of {len(entries)}. Pass query words, such as a setting's name, to narrow the list."
        if not query:
            result["note"] = (result.get("note", "") + " Settings only the user can change are left out unless your query matches them.").strip()
        return result

    def overview(self) -> Dict[str, Any]:
        """A short map of the agent's reach: setting sections with counts, other abilities, and what is off limits."""
        from .overview import build_overview

        return build_overview(self._registry)

    def get_entries(self, keys: List[str]) -> Dict[str, Any]:
        preferences = preferences_io.load_preferences()
        settings: List[Dict[str, Any]] = []
        unknown: List[str] = []
        for key in keys:
            entry = self._registry.get(key)
            if entry is None:
                unknown.append(key)
            else:
                settings.append(self.describe(entry, preferences))
        result: Dict[str, Any] = {"ok": not unknown, "settings": settings}
        if unknown:
            result["error"] = f"Unknown setting key(s): {', '.join(unknown)}. Use action list to see valid keys."
            result["unknown_keys"] = unknown
        return result

    def _readable_values(self, preferences: Any, overrides: Mapping[str, Any]) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for entry in self._registry.all():
            if entry.read is not None and entry.tier != Tier.HUMAN_ONLY:
                values[entry.key] = entry.read(preferences)
        values.update(overrides)
        return values

    def _rule_violation(self, preferences: Any, after_by_key: Mapping[str, Any]) -> Optional[str]:
        touched = frozenset(after_by_key)
        values = self._readable_values(preferences, after_by_key)
        for rule in self._registry.rules:
            if rule.keys & touched:
                message = rule.check(values)
                if message:
                    return message
        return None

    def _validate(self, requested: Any) -> Tuple[Optional[List[Tuple[ControlEntry, Any]]], Optional[Dict[str, Any]]]:
        if not isinstance(requested, list) or not requested:
            return None, _error("changes must be a non-empty list of {key, value} items.")
        if len(requested) > MAX_CHANGES_PER_CALL:
            return None, _error(f"Too many changes in one call ({len(requested)}); send at most {MAX_CHANGES_PER_CALL}.")
        parsed: List[Tuple[ControlEntry, Any]] = []
        problems: List[Dict[str, str]] = []
        seen: set = set()
        for item in requested:
            key = item.get("key") if isinstance(item, dict) else None
            if not isinstance(key, str) or not isinstance(item, dict) or "value" not in item:
                problems.append({"key": str(key), "problem": "Each change needs a key and a value."})
                continue
            if key in seen:
                problems.append({"key": key, "problem": "This key appears more than once."})
                continue
            seen.add(key)
            entry = self._registry.get(key)
            if entry is None:
                problems.append({"key": key, "problem": "Unknown setting. Use action list to see valid keys."})
                continue
            if not entry.changeable:
                problems.append(
                    {"key": key, "problem": f"{entry.label} cannot be changed by an agent. The user can change it in {entry.where_in_settings}."}
                )
                continue
            try:
                parsed.append((entry, entry.parse(item["value"])))  # type: ignore[misc]
            except ValueError as exc:
                problems.append({"key": key, "problem": str(exc)})
        if not problems and any(entry.change_alone for entry, _ in parsed):
            others = [entry for entry, _ in parsed if not entry.change_alone]
            if others:
                alone = ", ".join(entry.label for entry, _ in parsed if entry.change_alone)
                problems.append(
                    {
                        "key": ", ".join(entry.key for entry, _ in parsed if entry.change_alone),
                        "problem": f"{alone} can be changed only when the user asks for it by name, and only in a call that changes nothing else. Send it on its own, and leave it out of a palette or theme change.",
                    }
                )
        if problems:
            return None, _error("Nothing was changed. Fix these and send the whole batch again.", problems=problems)
        return parsed, None

    async def apply(
        self,
        requested: Any,
        *,
        reason: str = "",
        agent_task_id: Optional[str] = None,
        websocket_manager: Any = None,
    ) -> Dict[str, Any]:
        parsed, failure = self._validate(requested)
        if failure is not None or parsed is None:
            return failure or _error("Invalid request.")

        preferences = preferences_io.load_preferences()
        planned = [(entry, entry.read(preferences), raw) for entry, raw in parsed]  # type: ignore[misc]
        planned = [item for item in planned if not _same(item[1], item[2])]
        if not planned:
            return {"ok": True, "applied": False, "message": "Every setting already has the requested value, so nothing changed."}

        violation = self._rule_violation(preferences, {entry.key: after for entry, _, after in planned})
        if violation:
            return _error(f"Nothing was changed. {violation}")

        recent = self._journal.count_since(RATE_LIMIT_WINDOW_SECONDS)
        if recent + len(planned) > RATE_LIMIT_CHANGES:
            return _error(
                f"Too many setting changes recently ({recent} in the last {int(RATE_LIMIT_WINDOW_SECONDS // 60)} minutes; the limit is {RATE_LIMIT_CHANGES}). "
                "Stop and tell the user what you were trying to do, and let them make the change in Settings or ask again later."
            )

        approval_tiers = [entry.tier for entry, _, _ in planned if entry.tier in APPROVAL_TIERS]
        approved_by_user = False
        if approval_tiers:
            highest = Tier.PRIVACY if Tier.PRIVACY in approval_tiers else Tier.BEHAVIORAL
            outcome = await self._approvals.request(
                SettingsChangeApprovalRequest(
                    tier=highest.value,
                    reason=reason,
                    changes=[
                        {"key": entry.key, "label": entry.label, "before": entry.render(before), "after": entry.render(after)}
                        for entry, before, after in planned
                    ],
                    agent_task_id=agent_task_id,
                    websocket_manager=websocket_manager,
                )
            )
            if outcome == "busy":
                return _error("The user is already being asked to approve a settings change, so nothing was changed. Wait for that answer and do not ask again until it arrives.", outcome=outcome)
            if outcome == "unavailable":
                return _error("The user could not be asked to approve this change, so nothing was changed. Tell the user which setting you wanted changed.", outcome=outcome)
            if outcome != "approved":
                message = "The user did not respond in time, so nothing was changed." if outcome == "timed_out" else "The user declined this change, so nothing was changed."
                return _error(message, outcome=outcome)
            approved_by_user = True
            preferences = preferences_io.load_preferences()
            if any(not _same(entry.read(preferences), before) for entry, before, _ in planned):  # type: ignore[misc]
                return _error(
                    "A setting changed while the user was deciding, so the approved change was not applied. Read the settings again with action get and ask again if it is still wanted.",
                    outcome="stale",
                )
            violation = self._rule_violation(preferences, {entry.key: after for entry, _, after in planned})
            if violation:
                return _error(f"Nothing was changed. {violation}")

        for entry, _, after in planned:
            entry.write(preferences, after)  # type: ignore[misc]
        preferences_io.save_preferences(preferences)
        await self._publish({entry.publish_group for entry, _, _ in planned}, preferences, [entry.key for entry, _, _ in planned])

        record = self._journal.record(
            agent_task_id=agent_task_id,
            reason=reason,
            approved_by_user=approved_by_user,
            changes=[
                {
                    "key": entry.key,
                    "label": entry.label,
                    "before_raw": before,
                    "after_raw": after,
                    "before": entry.render(before),
                    "after": entry.render(after),
                }
                for entry, before, after in planned
            ],
        )
        return {
            "ok": True,
            "applied": True,
            "change_id": record["id"],
            "changes": [
                {"key": entry.key, "label": entry.label, "before": entry.render(before), "after": entry.render(after)}
                for entry, before, after in planned
            ],
            "approved_by_user": approved_by_user,
            "undo": "The user can ask you to undo this; call action undo.",
            "tell_the_user": "Tell the user exactly what you changed and that it can be undone.",
        }

    async def undo(self, change_id: Optional[str] = None) -> Dict[str, Any]:
        record = self._journal.get(change_id) if change_id else self._journal.latest_undoable()
        if record is None:
            return _error("There is no matching change to undo." if change_id else "There is no change to undo.")
        if record.get("undone"):
            return _error("That change was already undone.")

        preferences = preferences_io.load_preferences()
        restores: List[Tuple[ControlEntry, Dict[str, Any]]] = []
        for change in record.get("changes") or []:
            entry = self._registry.get(change.get("key", ""))
            if entry is None or entry.read is None or entry.write is None:
                return _error(f"{change.get('label') or change.get('key')} is no longer controllable, so the change was not undone.")
            if not _same(entry.read(preferences), change.get("after_raw")):
                return _error(
                    f"{entry.label} has been changed since, so nothing was undone, to avoid overwriting a newer choice. Ask the user what they want."
                )
            restores.append((entry, change))
        for entry, change in restores:
            entry.write(preferences, change.get("before_raw"))  # type: ignore[misc]
        preferences_io.save_preferences(preferences)
        await self._publish({entry.publish_group for entry, _ in restores}, preferences, [entry.key for entry, _ in restores])
        self._journal.mark_undone(record["id"])
        return {
            "ok": True,
            "undone": record["id"],
            "restored": [{"key": entry.key, "label": entry.label, "value": change.get("before")} for entry, change in restores],
        }

    async def _publish(self, groups: set, preferences: Any, keys: List[str]) -> None:
        for group in sorted(group for group in groups if group):
            publisher = self._publishers.get(group)
            if publisher is None:
                continue
            try:
                await publisher(preferences)
            except Exception:
                logger.warning("Could not publish the %s settings change to clients; it is saved.", group, exc_info=True)
        if self._change_notifier is not None:
            try:
                await self._change_notifier(keys)
            except Exception:
                logger.warning("Could not announce the settings change to clients; it is saved.", exc_info=True)


_ENGINE: Optional[AppControlEngine] = None


def get_app_control_engine() -> AppControlEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = AppControlEngine()
    return _ENGINE

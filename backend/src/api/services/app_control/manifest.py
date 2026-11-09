"""The catalog of Basil settings an agent may read or change, and the safety tier of each one."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Tuple


class Tier(str, Enum):
    """How much human involvement a change needs before it takes effect."""

    COSMETIC = "cosmetic"
    BEHAVIORAL = "behavioral"
    PRIVACY = "privacy"
    HUMAN_ONLY = "human_only"


APPROVAL_TIERS: Tuple[Tier, ...] = (Tier.BEHAVIORAL, Tier.PRIVACY)

EntryKind = Literal["color", "enum", "bool", "number", "text"]


def _identity(raw: Any) -> Any:
    return raw


@dataclass(frozen=True)
class ControlEntry:
    """One setting an agent can see, and usually change.

    `read` and `write` operate on the whole Preferences object and use the raw stored value. `parse` turns what the agent sent into that raw value and raises ValueError with a message the agent can act on. `render` turns a raw value into what the agent and the approval card display.
    """

    key: str
    label: str
    description: str
    kind: EntryKind
    tier: Tier
    where_in_settings: str
    publish_group: str = ""
    change_alone: bool = False
    covers: Tuple[str, ...] = ()
    allowed: Tuple[Any, ...] = ()
    parse: Optional[Callable[[Any], Any]] = None
    read: Optional[Callable[[Any], Any]] = None
    write: Optional[Callable[[Any, Any], None]] = None
    render: Callable[[Any], Any] = field(default=_identity)

    @property
    def changeable(self) -> bool:
        """True when an agent may change this entry, with approval if its tier requires it."""
        return self.tier != Tier.HUMAN_ONLY and self.write is not None and self.parse is not None


@dataclass(frozen=True)
class GroupRule:
    """A check across several entries at once; it runs only when a change touches one of `keys`.

    `check` receives every readable entry's raw value as it would be after the change, keyed by entry key, and returns a message for the agent when the result would be unacceptable.
    """

    keys: frozenset
    check: Callable[[Mapping[str, Any]], Optional[str]]


class ControlRegistry:
    """Holds the entries and the cross-entry rules; an agent can only touch what is registered here."""

    def __init__(self, entries: Tuple[ControlEntry, ...] = (), rules: Tuple[GroupRule, ...] = ()) -> None:
        self._entries: Dict[str, ControlEntry] = {}
        self._rules: List[GroupRule] = list(rules)
        for entry in entries:
            self.register(entry)

    def register(self, entry: ControlEntry) -> None:
        if entry.key in self._entries:
            raise ValueError(f"Duplicate app control entry: {entry.key}")
        self._entries[entry.key] = entry

    def add_rule(self, rule: GroupRule) -> None:
        self._rules.append(rule)

    @property
    def rules(self) -> Tuple[GroupRule, ...]:
        return tuple(self._rules)

    def get(self, key: str) -> Optional[ControlEntry]:
        return self._entries.get(key)

    def all(self) -> List[ControlEntry]:
        return list(self._entries.values())

    def search(self, query: str) -> List[ControlEntry]:
        """Entries whose key, label, or description contains every word of the query."""
        words = [word for word in query.lower().split() if word]
        if not words:
            return self.all()
        matches: List[ControlEntry] = []
        for entry in self._entries.values():
            haystack = f"{entry.key} {entry.label} {entry.description}".lower()
            if all(word in haystack for word in words):
                matches.append(entry)
        return matches

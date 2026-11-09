"""Builds a control entry for every setting the classification file lets an agent see, straight from the preference models."""

from __future__ import annotations

import enum
import re
from typing import Annotated, Any, Dict, Iterable, List, Set, Tuple

from pydantic import TypeAdapter, ValidationError

from .classification import (
    CHOICE_OVERRIDES,
    DESCRIPTION_OVERRIDES,
    POLICIES,
    SECTION_LABELS,
    TIME_OF_DAY_SETTINGS,
)
from .manifest import ControlEntry, Tier
from .preference_schema import SchemaField, iter_schema_fields

_TIME_OF_DAY = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def label_for(field: SchemaField) -> str:
    return field.name.replace("_", " ").strip().capitalize()


def where_in_settings(field: SchemaField) -> str:
    label = SECTION_LABELS.get(field.section, "")
    return f"Settings, {label} area" if label else "Settings"


def _render(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def _section_object(preferences: Any, field: SchemaField) -> Any:
    return getattr(preferences, field.section) if field.section else preferences


def _enum_member(choices: Tuple[Any, ...], value: Any) -> Any:
    text = value.strip().lower() if isinstance(value, str) else None
    for member in choices:
        if isinstance(member, enum.Enum):
            if member is value or (text is not None and (str(member.value).lower() == text or member.name.lower() == text)):
                return member
        elif isinstance(member, str) and text is not None and member.lower() == text:
            return member
    allowed = ", ".join(str(_render(member)) for member in choices)
    raise ValueError(f"Choose one of: {allowed}.")


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "on", "yes"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "off", "no"):
        return False
    raise ValueError("Use true or false.")


def make_parser(field: SchemaField, choices: Tuple[Any, ...]):
    """A function that turns what an agent sent into the stored value, or raises ValueError with a message the agent can act on."""
    adapter = TypeAdapter(Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation)

    def check_constraints(value: Any) -> Any:
        try:
            return adapter.validate_python(value)
        except ValidationError as exc:
            reasons = "; ".join(error["msg"] for error in exc.errors())
            raise ValueError(f"Not accepted: {reasons}.") from exc

    def parse(value: Any) -> Any:
        if field.kind == "bool":
            return _parse_bool(value)
        if field.kind in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError("Send a number.")
            if isinstance(value, str):
                try:
                    value = float(value) if field.kind == "float" else int(value)
                except ValueError:
                    raise ValueError("Send a number.") from None
            if field.kind == "int" and isinstance(value, float):
                if not value.is_integer():
                    raise ValueError("Send a whole number.")
                value = int(value)
            return check_constraints(value)
        if field.kind == "choice":
            return check_constraints(_enum_member(choices, value))
        if not isinstance(value, str):
            raise ValueError("Send text.")
        if choices:
            return str(_enum_member(choices, value))
        if field.path in TIME_OF_DAY_SETTINGS and not _TIME_OF_DAY.fullmatch(value.strip()):
            raise ValueError("Use a 24-hour local time written HH:MM, such as 03:00.")
        return check_constraints(value.strip() if field.path in TIME_OF_DAY_SETTINGS else value)

    return parse


def _entry_kind(field: SchemaField, choices: Tuple[Any, ...]) -> str:
    if field.kind == "bool":
        return "bool"
    if field.kind in ("int", "float"):
        return "number"
    if field.kind == "choice" or choices:
        return "enum"
    return "text"


def build_schema_entries(covered_by_curated: Iterable[str] = ()) -> Tuple[ControlEntry, ...]:
    """One entry per classified setting that no curated entry already covers. Settings an agent cannot change are listed without a way to write them."""
    skip: Set[str] = set(covered_by_curated)
    entries: List[ControlEntry] = []
    for field in iter_schema_fields():
        if field.path in skip:
            continue
        policy = POLICIES.get(field.path)
        if policy is None:
            continue
        description = DESCRIPTION_OVERRIDES.get(field.path) or field.description
        label = label_for(field)
        if policy.tier == Tier.HUMAN_ONLY:
            entries.append(
                ControlEntry(
                    key=field.path,
                    label=label,
                    description=f"{description} Agents cannot change this. {policy.reason}".strip(),
                    kind="text",
                    tier=Tier.HUMAN_ONLY,
                    where_in_settings=where_in_settings(field),
                    covers=(field.path,),
                )
            )
            continue
        override = CHOICE_OVERRIDES.get(field.path)
        choices: Tuple[Any, ...] = tuple(override) if override else field.choices
        section_name, name = field.section, field.name

        def read(preferences: Any, _field: SchemaField = field) -> Any:
            return getattr(_section_object(preferences, _field), _field.name)

        def write(preferences: Any, raw: Any, _field: SchemaField = field, _choices: Tuple[Any, ...] = choices) -> None:
            if _field.kind == "choice":
                raw = _enum_member(_choices, raw)
            setattr(_section_object(preferences, _field), _field.name, raw)

        entries.append(
            ControlEntry(
                key=field.path,
                label=label,
                description=description,
                kind=_entry_kind(field, choices),  # type: ignore[arg-type]
                tier=policy.tier,
                where_in_settings=where_in_settings(field),
                publish_group=policy.group,
                covers=(field.path,),
                allowed=tuple(_render(choice) for choice in choices) if choices else (),
                parse=make_parser(field, choices),
                read=read,
                write=write,
                render=_render,
            )
        )
    return tuple(entries)

"""Reads Basil's preference models and lists every setting in them, so no setting can be added without being noticed."""

from __future__ import annotations

import enum
import typing
from dataclasses import dataclass
from typing import Any, List, Literal, Tuple

from pydantic import BaseModel

SchemaKind = Literal["bool", "int", "float", "str", "choice", "complex"]


@dataclass(frozen=True)
class SchemaField:
    """One leaf setting: `path` is "section.name", or just "name" for a top-level setting that has no section."""

    path: str
    section: str
    name: str
    annotation: Any
    kind: SchemaKind
    description: str
    metadata: Tuple[Any, ...]
    choices: Tuple[Any, ...] = ()


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def classify_annotation(annotation: Any) -> Tuple[SchemaKind, Tuple[Any, ...]]:
    """The kind of value a setting holds, and its fixed choices when it has them. Lists, dicts, tuples, models and optional values are "complex"."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return "choice", tuple(typing.get_args(annotation))
    if origin is not None:
        return "complex", ()
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return "choice", tuple(annotation)
        if _is_model(annotation):
            return "complex", ()
        if annotation is bool:
            return "bool", ()
        if annotation is int:
            return "int", ()
        if annotation is float:
            return "float", ()
        if annotation is str:
            return "str", ()
    return "complex", ()


def iter_schema_fields(preferences_class: Any = None) -> List[SchemaField]:
    """Every leaf setting of the Preferences model, in declaration order."""
    if preferences_class is None:
        from api.core.models.preferences import Preferences as preferences_class

    fields: List[SchemaField] = []
    for section_name, section_field in preferences_class.model_fields.items():
        if _is_model(section_field.annotation):
            for name, leaf in section_field.annotation.model_fields.items():
                kind, choices = classify_annotation(leaf.annotation)
                fields.append(
                    SchemaField(
                        path=f"{section_name}.{name}",
                        section=section_name,
                        name=name,
                        annotation=leaf.annotation,
                        kind=kind,
                        description=leaf.description or "",
                        metadata=tuple(leaf.metadata),
                        choices=choices,
                    )
                )
        else:
            kind, choices = classify_annotation(section_field.annotation)
            fields.append(
                SchemaField(
                    path=section_name,
                    section="",
                    name=section_name,
                    annotation=section_field.annotation,
                    kind=kind,
                    description=section_field.description or "",
                    metadata=tuple(section_field.metadata),
                    choices=choices,
                )
            )
    return fields

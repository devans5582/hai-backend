"""Validate a plain record (dict) against an entity definition.

This is the manifest-level counterpart of the generated Pydantic models. It is
used by the validator to check the example records, and by tests. Error codes
are stable so examples can name the error they expect.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from hai_ontology.conditions import UnsafeExpressionError, evaluate
from hai_ontology.meta import COMMON_FIELD_NAMES, EntityDef, FieldDef, FieldType, Manifest

__all__ = ["RecordError", "validate_record"]


@dataclass(frozen=True)
class RecordError:
    code: str
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f" ({self.field})" if self.field else ""
        return f"{self.code}{where}: {self.message}"


def validate_record(manifest: Manifest, entity: EntityDef, record: dict[str, Any]) -> list[RecordError]:
    errors: list[RecordError] = []
    fields = entity.field_map
    for key in record:
        if key not in fields and key not in COMMON_FIELD_NAMES:
            errors.append(RecordError("E_UNKNOWN_FIELD", key, f"{entity.name} has no field {key!r}"))
    for f in entity.all_fields:
        value = record.get(f.name)
        if value is None:
            if f.required and f.default is None:
                errors.append(RecordError("E_REQUIRED", f.name, "required field is missing"))
            continue
        errors.extend(_check_type(manifest, f, value))
    if errors:
        return errors
    namespace = {f.name: record.get(f.name, f.default) for f in entity.all_fields}
    for check in entity.checks:
        try:
            ok = evaluate(check.py, namespace)
        except UnsafeExpressionError as exc:
            errors.append(RecordError("E_CHECK_UNSAFE", None, f"{check.id}: {exc}"))
            continue
        if not ok:
            errors.append(RecordError(check.id, None, check.description))
    return errors


def _check_type(manifest: Manifest, f: FieldDef, value: Any) -> list[RecordError]:
    kind = f.type
    if kind is FieldType.ARRAY:
        if not isinstance(value, list):
            return [RecordError("E_TYPE", f.name, "expected a list")]
        assert f.items is not None
        item_def = FieldDef(name=f.name, type=f.items, vocabulary=f.vocabulary, description=f.description)
        out: list[RecordError] = []
        for item in value:
            out.extend(_check_type(manifest, item_def, item))
        return out
    if kind is FieldType.ENUM:
        assert f.vocabulary is not None
        voc = manifest.vocabularies.get(f.vocabulary)
        if voc is None:
            return [RecordError("E_REF_UNKNOWN_VOCAB", f.name, f"vocabulary {f.vocabulary} does not exist")]
        if not isinstance(value, str) or value not in voc.codes:
            return [RecordError("E_ENUM_VALUE", f.name, f"{value!r} is not a value of {f.vocabulary}")]
        return []
    if kind in (FieldType.UUID, FieldType.REF):
        if isinstance(value, uuid.UUID):
            return []
        try:
            uuid.UUID(str(value))
        except ValueError:
            return [RecordError("E_TYPE", f.name, "expected a UUID")]
        return []
    if kind is FieldType.TEXT:
        return [] if isinstance(value, str) else [RecordError("E_TYPE", f.name, "expected text")]
    if kind in (FieldType.INT, FieldType.BIGINT):
        if isinstance(value, bool) or not isinstance(value, int):
            return [RecordError("E_TYPE", f.name, "expected an integer")]
        return _range(f, value)
    if kind is FieldType.NUMERIC:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return [RecordError("E_TYPE", f.name, "expected a number")]
        return _range(f, float(value))
    if kind is FieldType.BOOL:
        return [] if isinstance(value, bool) else [RecordError("E_TYPE", f.name, "expected a boolean")]
    if kind is FieldType.TIMESTAMP:
        if isinstance(value, dt.datetime):
            return []
        try:
            dt.datetime.fromisoformat(str(value))
        except ValueError:
            return [RecordError("E_TYPE", f.name, "expected an ISO timestamp")]
        return []
    if kind is FieldType.DATE:
        if isinstance(value, dt.date):
            return []
        try:
            dt.date.fromisoformat(str(value))
        except ValueError:
            return [RecordError("E_TYPE", f.name, "expected an ISO date")]
        return []
    return []  # json accepts anything


def _range(f: FieldDef, value: float) -> list[RecordError]:
    if f.min is not None and value < f.min:
        return [RecordError("E_RANGE", f.name, f"{value} is below the minimum {f.min}")]
    if f.max is not None and value > f.max:
        return [RecordError("E_RANGE", f.name, f"{value} is above the maximum {f.max}")]
    return []

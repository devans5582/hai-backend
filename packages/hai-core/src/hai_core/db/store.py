"""Typed store over the generated models and tables.

``insert`` is audited for decision-bearing entities. ``update`` is audited and
refuses append-only entities and immutable fields before the database would.
"""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Connection, Table, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from hai_core.audit import append_event
from hai_core.errors import AppendOnlyError, ImmutableFieldError, NotFoundError, ValidationFailedError
from hai_core.generated.models import EntityBase
from hai_core.generated.tables import TABLES
from hai_ontology.meta import Manifest

M = TypeVar("M", bound=EntityBase)

# Writes to these entities are recorded in the audit chain.
DECISION_BEARING: frozenset[str] = frozenset(
    {
        "Organization",
        "Incident",
        "Remediation",
        "EvidenceLink",
        "Assessment",
        "EvidenceSnapshot",
        "CriterionFinding",
        "CriterionDecision",
        "PillarScore",
        "AssessmentResult",
        "CertificationDecision",
        "Review",
        "MethodologyVersion",
    }
)


def _plain(value: Any) -> Any:
    if hasattr(value, "value") and isinstance(getattr(value, "value", None), str):
        return value.value
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class Store:
    def __init__(self, conn: Connection, *, actor: str, manifest: Manifest, audit: bool = True) -> None:
        self.conn = conn
        self.actor = actor
        self.manifest = manifest
        self.audit = audit

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def table_for(model: type[EntityBase] | EntityBase) -> Table:
        return TABLES[model.__entity__]

    def _hydrate(self, cls: type[M], row: Any) -> M:
        return cls.model_validate(dict(row._mapping))

    # -------------------------------------------------------------------- reads
    def get(self, cls: type[M], id_: UUID) -> M | None:
        table = self.table_for(cls)
        row = self.conn.execute(select(table).where(table.c.id == id_)).first()
        return self._hydrate(cls, row) if row is not None else None

    def require(self, cls: type[M], id_: UUID) -> M:
        found = self.get(cls, id_)
        if found is None:
            raise NotFoundError(f"{cls.__entity__} {id_} not found")
        return found

    def find(
        self,
        cls: type[M],
        *,
        where: dict[str, Any] | None = None,
        order_by: str = "created_at",
        descending: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[M]:
        table = self.table_for(cls)
        stmt = select(table)
        for key, value in (where or {}).items():
            col = table.c[key]
            stmt = stmt.where(
                col.in_([_plain(v) for v in value]) if isinstance(value, list | tuple | set) else col == _plain(value)
            )
        col = table.c[order_by]
        stmt = stmt.order_by(col.desc() if descending else col.asc(), table.c.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        return [self._hydrate(cls, r) for r in self.conn.execute(stmt).all()]

    def count(self, cls: type[EntityBase], *, where: dict[str, Any] | None = None) -> int:
        table = self.table_for(cls)
        stmt = select(func.count()).select_from(table)
        for key, value in (where or {}).items():
            col = table.c[key]
            stmt = stmt.where(
                col.in_([_plain(v) for v in value]) if isinstance(value, list | tuple | set) else col == _plain(value)
            )
        return int(self.conn.execute(stmt).scalar_one())

    def first(
        self, cls: type[M], *, where: dict[str, Any], order_by: str = "created_at", descending: bool = True
    ) -> M | None:
        rows = self.find(cls, where=where, order_by=order_by, descending=descending, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------------- writes
    def insert(self, model: M, *, reason: str | None = None) -> M:
        table = self.table_for(model)
        row = model.row()
        result = self.conn.execute(
            pg_insert(table).values(**row).returning(table.c.created_at, table.c.created_by)
        ).first()
        assert result is not None
        stored = model.model_copy(update={"created_at": result[0], "created_by": result[1]})
        if self.audit and model.__entity__ in DECISION_BEARING:
            append_event(
                self.conn,
                actor=self.actor,
                action="insert",
                subject_type=model.__entity__,
                subject_id=model.id,
                after=stored.row(),
                reason=reason,
            )
        return stored

    def insert_many(self, models: list[M]) -> list[M]:
        return [self.insert(m) for m in models]

    def update(self, cls: type[M], id_: UUID, changes: dict[str, Any], *, reason: str | None = None) -> M:
        entity = self.manifest.entity(cls.__entity__)
        if entity.insert_only:
            raise AppendOnlyError(f"{entity.name} is insert-only (IC-02); add a superseding row instead")
        immutable = set(entity.immutable_fields)
        fields = entity.field_map
        for key in changes:
            if key in immutable:
                raise ImmutableFieldError(f"{entity.name}.{key} cannot change")
            if key not in fields:
                raise ValidationFailedError(f"{entity.name} has no field {key!r}")
        before = self.require(cls, id_)
        table = self.table_for(cls)
        values = {k: _plain(v) for k, v in changes.items()}
        self.conn.execute(update(table).where(table.c.id == id_).values(**values))
        after = self.require(cls, id_)
        if self.audit and entity.name in DECISION_BEARING:
            append_event(
                self.conn,
                actor=self.actor,
                action="update",
                subject_type=entity.name,
                subject_id=id_,
                before={k: before.row().get(k) for k in changes},
                after={k: after.row().get(k) for k in changes},
                reason=reason,
            )
        return after

    def upsert(self, model: M, *, conflict_fields: list[str], update_fields: list[str] | None = None) -> M:
        """Insert or, on conflict over ``conflict_fields``, update ``update_fields`` (default: all others)."""
        table = self.table_for(model)
        row = model.row()
        skip = {"id", "created_at", "created_by", *conflict_fields}
        to_update = update_fields or [k for k in row if k not in skip]
        base = pg_insert(table).values(**row)
        stmt = base.on_conflict_do_update(index_elements=conflict_fields, set_={k: base.excluded[k] for k in to_update})
        result = self.conn.execute(stmt.returning(table)).first()
        assert result is not None
        return self._hydrate(type(model), result)

    def supersede(self, old: M, new: M, *, reason: str | None = None) -> M:
        """Insert ``new`` as the superseding row of ``old`` (append-only correction)."""
        if "supersedes_id" not in type(new).model_fields:
            raise ValidationFailedError(f"{new.__entity__} is not supersedable")
        replacement = new.model_copy(update={"supersedes_id": old.id})
        return self.insert(replacement, reason=reason)

    def record_action(
        self,
        action: str,
        subject_type: str,
        subject_id: UUID | None,
        *,
        reason: str | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        append_event(
            self.conn,
            actor=self.actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            after=after,
            reason=reason,
        )

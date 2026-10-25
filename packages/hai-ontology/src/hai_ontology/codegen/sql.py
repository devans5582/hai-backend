"""PostgreSQL baseline generator.

Emits one enum per vocabulary, one table per entity with common columns, FKs
from the relationship catalogue, CHECK constraints for declarative checks and
ranges, triggers for append-only tables, immutable columns and legal state
transitions, writer-role grants, and table and column comments.
"""

from __future__ import annotations

from hai_ontology.codegen.common import header
from hai_ontology.meta import (
    CheckDef,
    EntityDef,
    FieldDef,
    FieldType,
    Manifest,
    Mutability,
    RelationDef,
    VocabularyDef,
)

SQL_TYPES: dict[FieldType, str] = {
    FieldType.UUID: "uuid",
    FieldType.TEXT: "text",
    FieldType.INT: "integer",
    FieldType.BIGINT: "bigint",
    FieldType.NUMERIC: "numeric",
    FieldType.BOOL: "boolean",
    FieldType.TIMESTAMP: "timestamptz",
    FieldType.DATE: "date",
    FieldType.JSON: "jsonb",
    FieldType.REF: "uuid",
}


def q(text: str) -> str:
    """Quote a string literal for SQL."""
    return "'" + text.replace("'", "''") + "'"


def column_type(manifest: Manifest, f: FieldDef) -> str:
    s = manifest.schema_name
    if f.type is FieldType.ENUM:
        return f"{s}.{f.vocabulary}"
    if f.type is FieldType.ARRAY:
        assert f.items is not None
        if f.items is FieldType.ENUM:
            return f"{s}.{f.vocabulary}[]"
        return SQL_TYPES[f.items] + "[]"
    return SQL_TYPES[f.type]


def default_sql(f: FieldDef) -> str:
    if f.default is None:
        return ""
    if isinstance(f.default, bool):
        return f" DEFAULT {'true' if f.default else 'false'}"
    if isinstance(f.default, int | float):
        return f" DEFAULT {f.default}"
    return f" DEFAULT {q(str(f.default))}"


def column_ddl(manifest: Manifest, f: FieldDef) -> str:
    parts = [f"    {f.name} {column_type(manifest, f)}"]
    if f.required:
        parts.append(" NOT NULL")
    parts.append(default_sql(f))
    if f.unique:
        parts.append(" UNIQUE")
    return "".join(parts)


def enum_ddl(manifest: Manifest, voc: VocabularyDef) -> str:
    values = ", ".join(q(v.code) for v in voc.ordered_values)
    return f"CREATE TYPE {manifest.schema_name}.{voc.code} AS ENUM ({values});\n"


def _range_checks(e: EntityDef) -> list[str]:
    out: list[str] = []
    for f in e.all_fields:
        conds = []
        if f.min is not None:
            conds.append(f"{f.name} >= {_num(f.min)}")
        if f.max is not None:
            conds.append(f"{f.name} <= {_num(f.max)}")
        if conds:
            out.append(
                f"    CONSTRAINT ck_{e.table}_{f.name}_range CHECK ({f.name} IS NULL OR ({' AND '.join(conds)}))"
            )
    return out


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def check_name(e: EntityDef, c: CheckDef) -> str:
    return f"ck_{e.table}_{c.id.lower().replace('-', '_')}"


def table_ddl(manifest: Manifest, e: EntityDef) -> str:
    s = manifest.schema_name
    lines = [
        f"CREATE TABLE {s}.{e.table} (",
        "    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),",
        "    ontology_version text NOT NULL,",
        "    created_at timestamptz NOT NULL DEFAULT now(),",
        "    created_by text NOT NULL DEFAULT coalesce(current_setting('hai.actor', true), 'unknown'),",
    ]
    cols = [column_ddl(manifest, f) for f in e.all_fields]
    constraints = [f"    CONSTRAINT {check_name(e, c)} CHECK ({c.sql})" for c in e.checks]
    constraints += _range_checks(e)
    constraints += [f"    CONSTRAINT uq_{e.table}_{'_'.join(group)} UNIQUE ({', '.join(group)})" for group in e.unique]
    body = cols + constraints
    lines.append(",\n".join(body))
    lines.append(");")
    return "\n".join(lines) + "\n"


def add_column(manifest: Manifest, e: EntityDef, f: FieldDef) -> str:
    return f"ALTER TABLE {manifest.schema_name}.{e.table} ADD COLUMN IF NOT EXISTS {column_ddl(manifest, f).strip()};\n"


def alter_default(manifest: Manifest, e: EntityDef, f: FieldDef) -> str:
    d = default_sql(f).strip()
    if not d:
        return f"ALTER TABLE {manifest.schema_name}.{e.table} ALTER COLUMN {f.name} DROP DEFAULT;\n"
    return f"ALTER TABLE {manifest.schema_name}.{e.table} ALTER COLUMN {f.name} SET {d};\n"


def add_check(manifest: Manifest, e: EntityDef, c: CheckDef) -> str:
    return f"ALTER TABLE {manifest.schema_name}.{e.table} ADD CONSTRAINT {check_name(e, c)} CHECK ({c.sql});\n"


def fk_block(manifest: Manifest, e: EntityDef) -> str:
    s = manifest.schema_name
    out = []
    for fk in manifest.fks_for(e.name):
        target = manifest.entity(fk.to)
        out.append(
            f"ALTER TABLE {s}.{e.table} ADD CONSTRAINT fk_{e.table}_{fk.field} "
            f"FOREIGN KEY ({fk.field}) REFERENCES {s}.{target.table}(id);"
        )
        out.append(f"CREATE INDEX IF NOT EXISTS ix_{e.table}_{fk.field} ON {s}.{e.table} ({fk.field});")
    return "\n".join(out) + ("\n" if out else "")


def fk_block_for_relation(manifest: Manifest, rel: RelationDef) -> str:
    s = manifest.schema_name
    out = []
    for fk in rel.fks:
        e = manifest.entity(fk.entity)
        target = manifest.entity(fk.to)
        out.append(
            f"ALTER TABLE {s}.{e.table} ADD CONSTRAINT fk_{e.table}_{fk.field} "
            f"FOREIGN KEY ({fk.field}) REFERENCES {s}.{target.table}(id);"
        )
    return "\n".join(out) + ("\n" if out else "")


def trigger_block(manifest: Manifest, e: EntityDef) -> str:
    """Append-only, immutable-column and transition triggers for one entity."""
    s = manifest.schema_name
    out: list[str] = []
    if e.mutability is not Mutability.MUTABLE:
        out.append(
            f"CREATE OR REPLACE TRIGGER trg_{e.table}_append_only BEFORE UPDATE OR DELETE ON {s}.{e.table}\n"
            f"    FOR EACH ROW EXECUTE FUNCTION {s}.refuse_change();"
        )
    immutable = [f for f in e.immutable_fields if e.mutability is Mutability.MUTABLE]
    if immutable:
        conds = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in immutable)
        out.append(
            f"CREATE OR REPLACE FUNCTION {s}.trgfn_{e.table}_immutable() RETURNS trigger LANGUAGE plpgsql AS $$\n"
            f"BEGIN\n"
            f"    IF {conds} THEN\n"
            f"        RAISE EXCEPTION 'HAI_IMMUTABLE: {e.table} columns {', '.join(immutable)} cannot change'\n"
            f"            USING ERRCODE = 'integrity_constraint_violation';\n"
            f"    END IF;\n"
            f"    RETURN NEW;\n"
            f"END $$;\n"
            f"CREATE OR REPLACE TRIGGER trg_{e.table}_immutable BEFORE UPDATE ON {s}.{e.table}\n"
            f"    FOR EACH ROW EXECUTE FUNCTION {s}.trgfn_{e.table}_immutable();"
        )
    if e.transitions:
        out.append(transition_trigger(manifest, e))
    return "\n".join(out) + ("\n" if out else "")


def transition_trigger(manifest: Manifest, e: EntityDef) -> str:
    assert e.transitions is not None
    s = manifest.schema_name
    voc = manifest.vocabulary(e.transitions.vocabulary)
    fld = e.transitions.field
    assert voc.transitions is not None
    rows = []
    for src, dests in voc.transitions.items():
        for d in dests:
            rows.append(f"({q(src)}, {q(d)})")
    values = ",\n            ".join(rows) if rows else "(NULL, NULL)"
    return (
        f"CREATE OR REPLACE FUNCTION {s}.trgfn_{e.table}_{fld}_transition() RETURNS trigger LANGUAGE plpgsql AS $$\n"
        f"BEGIN\n"
        f"    IF NEW.{fld} IS DISTINCT FROM OLD.{fld} AND NOT EXISTS (\n"
        f"        SELECT 1 FROM (VALUES\n            {values}\n        ) AS t(src, dst)\n"
        f"        WHERE t.src = OLD.{fld}::text AND t.dst = NEW.{fld}::text\n"
        f"    ) THEN\n"
        f"        RAISE EXCEPTION 'HAI_TRANSITION: {e.table}.{fld} cannot move from % to %', OLD.{fld}, NEW.{fld}\n"
        f"            USING ERRCODE = 'integrity_constraint_violation';\n"
        f"    END IF;\n"
        f"    RETURN NEW;\n"
        f"END $$;\n"
        f"CREATE OR REPLACE TRIGGER trg_{e.table}_{fld}_transition BEFORE UPDATE OF {fld} ON {s}.{e.table}\n"
        f"    FOR EACH ROW EXECUTE FUNCTION {s}.trgfn_{e.table}_{fld}_transition();"
    )


def transition_blocks_for_vocabulary(manifest: Manifest, vocabulary: str) -> str:
    return "".join(
        transition_trigger(manifest, e) + "\n"
        for e in manifest.entities
        if e.transitions and e.transitions.vocabulary == vocabulary
    )


def grant_block(manifest: Manifest, e: EntityDef) -> str:
    s = manifest.schema_name
    roles = ", ".join(r.code for r in manifest.ontology.roles)
    out = [f"GRANT SELECT ON {s}.{e.table} TO {roles};"]
    privs = "INSERT" if e.mutability is not Mutability.MUTABLE else "INSERT, UPDATE"
    out.append(f"GRANT {privs} ON {s}.{e.table} TO {', '.join(e.writers)};")
    return "\n".join(out) + "\n"


def comment_block(manifest: Manifest, e: EntityDef) -> str:
    s = manifest.schema_name
    out = [f"COMMENT ON TABLE {s}.{e.table} IS {q(e.description)};"]
    for f in e.all_fields:
        out.append(f"COMMENT ON COLUMN {s}.{e.table}.{f.name} IS {q(f.description)};")
    return "\n".join(out) + "\n"


def table_block(manifest: Manifest, e: EntityDef) -> str:
    """Everything for one new table: DDL, FKs, triggers, grants, comments."""
    return "\n".join(
        part
        for part in (
            table_ddl(manifest, e),
            fk_block(manifest, e),
            trigger_block(manifest, e),
            grant_block(manifest, e),
            comment_block(manifest, e),
        )
        if part
    )


def baseline(manifest: Manifest) -> str:
    """The complete baseline migration."""
    s = manifest.schema_name
    parts: list[str] = [header(manifest, "--"), "\n"]
    parts.append("-- Roles (NOLOGIN; granted to the application user by the operator)\n")
    for role in manifest.ontology.roles:
        parts.append(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role.code}') THEN "
            f"CREATE ROLE {role.code} NOLOGIN; END IF; END $$;\n"
        )
    roles = ", ".join(r.code for r in manifest.ontology.roles)
    parts.append(f"\nCREATE SCHEMA IF NOT EXISTS {s};\nGRANT USAGE ON SCHEMA {s} TO {roles};\n")
    parts.append(
        f"\nCREATE TABLE {s}.schema_versions (\n"
        f"    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),\n"
        f"    ontology_version text NOT NULL,\n"
        f"    methodology_version text NOT NULL,\n"
        f"    manifest_hash text NOT NULL,\n"
        f"    applied_at timestamptz NOT NULL DEFAULT now()\n"
        f");\n"
        f"INSERT INTO {s}.schema_versions (ontology_version, methodology_version, manifest_hash) VALUES "
        f"({q(manifest.ontology_version)}, {q(manifest.methodology_version)}, {q(manifest.hash)});\n"
        f"GRANT SELECT ON {s}.schema_versions TO {roles};\n"
    )
    parts.append(
        f"\nCREATE OR REPLACE FUNCTION {s}.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$\n"
        f"BEGIN\n"
        f"    RAISE EXCEPTION 'HAI_APPEND_ONLY: % is insert-only (IC-02)', TG_TABLE_NAME\n"
        f"        USING ERRCODE = 'integrity_constraint_violation';\n"
        f"END $$;\n"
    )
    parts.append("\n-- Enums: one per vocabulary\n")
    for code in sorted(manifest.vocabularies):
        parts.append(enum_ddl(manifest, manifest.vocabularies[code]))
    parts.append("\n-- Tables\n")
    ordered = manifest.tables_in_dependency_order()
    for e in ordered:
        parts.append("\n" + table_ddl(manifest, e))
    parts.append("\n-- Foreign keys from the relationship catalogue\n")
    for e in ordered:
        parts.append(fk_block(manifest, e))
    parts.append("\n-- Triggers: append-only tables, immutable columns, legal transitions\n")
    for e in ordered:
        parts.append(trigger_block(manifest, e))
    parts.append("\n-- Writer role grants (IC-12)\n")
    for e in ordered:
        parts.append(grant_block(manifest, e))
    parts.append("\n-- Comments\n")
    for e in ordered:
        parts.append(comment_block(manifest, e))
    return "".join(parts)

"""Python generators: StrEnums, Pydantic entity models and SQLAlchemy Core tables."""

from __future__ import annotations

import pprint

from hai_ontology.codegen.common import const_name, header
from hai_ontology.meta import EntityDef, FieldDef, FieldType, Manifest, Mutability

PY_TYPES: dict[FieldType, str] = {
    FieldType.UUID: "UUID",
    FieldType.TEXT: "str",
    FieldType.INT: "int",
    FieldType.BIGINT: "int",
    FieldType.NUMERIC: "float",
    FieldType.BOOL: "bool",
    FieldType.TIMESTAMP: "datetime",
    FieldType.DATE: "date",
    FieldType.JSON: "Any",
    FieldType.REF: "UUID",
}


def _lit(obj: object) -> str:
    """A deterministic Python literal for nested dicts, lists and scalars."""
    return pprint.pformat(obj, width=100, sort_dicts=True)


def enum_class_name(vocab_code: str) -> str:
    return "".join(p.capitalize() for p in vocab_code.split("_"))


def _py_type(f: FieldDef) -> str:
    if f.type is FieldType.ENUM:
        assert f.vocabulary is not None
        return enum_class_name(f.vocabulary)
    if f.type is FieldType.ARRAY:
        assert f.items is not None
        if f.items is FieldType.ENUM:
            assert f.vocabulary is not None
            return f"list[{enum_class_name(f.vocabulary)}]"
        return f"list[{PY_TYPES[f.items]}]"
    return PY_TYPES[f.type]


def _py_default(f: FieldDef) -> str:
    if f.default is None:
        return "None"
    if f.type is FieldType.ENUM:
        assert f.vocabulary is not None
        return f"{enum_class_name(f.vocabulary)}.{const_name(str(f.default))}"
    if isinstance(f.default, bool):
        return "True" if f.default else "False"
    if isinstance(f.default, int | float):
        return repr(f.default)
    return repr(str(f.default))


def enums_module(manifest: Manifest) -> str:
    out = [
        header(manifest, "#"),
        '"""Vocabularies as StrEnums, with labels, attributes, aliases and transitions."""\n',
    ]
    out.append("from __future__ import annotations\n\nfrom enum import StrEnum\nfrom typing import Any\n\n")
    out.append(f'ONTOLOGY_VERSION = "{manifest.ontology_version}"\n')
    out.append(f'METHODOLOGY_VERSION = "{manifest.methodology_version}"\n')
    out.append(f'RULESET_VERSION = "{manifest.ruleset.version}"\n')
    out.append(f'MANIFEST_HASH = "{manifest.hash}"\n\n')
    for code in sorted(manifest.vocabularies):
        voc = manifest.vocabularies[code]
        out.append(f"\nclass {enum_class_name(code)}(StrEnum):\n")
        out.append(f'    """{voc.title}: {voc.description}"""\n\n')
        for v in voc.ordered_values:
            out.append(f'    {const_name(v.code)} = "{v.code}"\n')
    out.append("\n\nVOCABULARIES: dict[str, type[StrEnum]] = {\n")
    for code in sorted(manifest.vocabularies):
        out.append(f'    "{code}": {enum_class_name(code)},\n')
    out.append("}\n")
    labels = {code: {v.code: v.label for v in voc.values} for code, voc in sorted(manifest.vocabularies.items())}
    out.append(f"\nLABELS: dict[str, dict[str, str]] = {_lit(labels)}\n")
    attrs = {
        code: {v.code: v.attributes for v in voc.values if v.attributes}
        for code, voc in sorted(manifest.vocabularies.items())
        if voc.attributes
    }
    out.append(f"\nATTRIBUTES: dict[str, dict[str, dict[str, Any]]] = {_lit(attrs)}\n")
    ranks = {
        code: {v.code: v.rank for v in voc.values} for code, voc in sorted(manifest.vocabularies.items()) if voc.ordered
    }
    out.append(f"\nRANKS: dict[str, dict[str, int]] = {_lit(ranks)}\n")
    aliases = {
        code: {alias: v.code for v in voc.values for alias in v.aliases}
        for code, voc in sorted(manifest.vocabularies.items())
        if any(v.aliases for v in voc.values)
    }
    out.append(f"\nALIASES: dict[str, dict[str, str]] = {_lit(aliases)}\n")
    transitions = {
        code: voc.transitions for code, voc in sorted(manifest.vocabularies.items()) if voc.transitions is not None
    }
    out.append(f"\nTRANSITIONS: dict[str, dict[str, list[str]]] = {_lit(transitions)}\n")
    out.append(
        "\n\ndef resolve_alias(vocabulary: str, text: str) -> str | None:\n"
        '    """Return the value code for a code or alias (case-insensitive), or None."""\n'
        "    needle = text.strip().lower()\n"
        "    for code in LABELS[vocabulary]:\n"
        "        if code.lower() == needle:\n"
        "            return code\n"
        "    for alias, code in ALIASES.get(vocabulary, {}).items():\n"
        "        if alias.lower() == needle:\n"
        "            return code\n"
        "    return None\n"
    )
    out.append(
        "\n\ndef attribute(vocabulary: str, code: str, key: str) -> Any:\n"
        '    """Typed attribute of a vocabulary value."""\n'
        "    return ATTRIBUTES[vocabulary][code][key]\n"
    )
    return "".join(out)


def models_module(manifest: Manifest) -> str:
    out = [
        header(manifest, "#"),
        '"""Pydantic entity models. Frozen where the entity is immutable or append-only."""\n',
    ]
    out.append(
        "from __future__ import annotations\n\n"
        "from datetime import date, datetime\n"
        "from typing import Any, ClassVar\n"
        "from uuid import UUID, uuid4\n\n"
        "from pydantic import BaseModel, ConfigDict, Field, model_validator\n\n"
        "from hai_ontology.conditions import evaluate\n\n"
        "from hai_core.generated.enums import (  # noqa: F401\n"
    )
    for code in sorted(manifest.vocabularies):
        out.append(f"    {enum_class_name(code)},\n")
    out.append(")\n\n")
    out.append(f'ONTOLOGY_VERSION = "{manifest.ontology_version}"\n\n\n')
    out.append(
        "class EntityBase(BaseModel):\n"
        '    """Common columns every table carries."""\n\n'
        '    model_config = ConfigDict(extra="forbid", use_enum_values=False)\n'
        '    __entity__: ClassVar[str] = ""\n'
        '    __table__: ClassVar[str] = ""\n'
        "    __checks__: ClassVar[tuple[tuple[str, str, str], ...]] = ()\n\n"
        "    id: UUID = Field(default_factory=uuid4)\n"
        "    ontology_version: str = ONTOLOGY_VERSION\n"
        "    created_at: datetime | None = None\n"
        "    created_by: str | None = None\n\n"
        '    @model_validator(mode="after")\n'
        "    def _run_checks(self) -> EntityBase:\n"
        "        if not self.__checks__:\n"
        "            return self\n"
        "        ns = {k: (v.value if hasattr(v, 'value') else v) for k, v in self.__dict__.items()}\n"
        "        for check_id, expr, description in self.__checks__:\n"
        "            if not evaluate(expr, ns):\n"
        '                raise ValueError(f"{check_id}: {description}")\n'
        "        return self\n\n"
        "    def row(self) -> dict[str, Any]:\n"
        '        """Column values for an insert, enums as their codes, omitting unset common columns."""\n'
        '        data = self.model_dump(mode="python")\n'
        '        for k in ("created_at", "created_by"):\n'
        "            if data.get(k) is None:\n"
        "                data.pop(k, None)\n"
        "        return {k: (v.value if hasattr(v, 'value') else v) for k, v in data.items()}\n"
    )
    for e in manifest.entities:
        out.append(_model_class(e))
    out.append("\n\nMODELS: dict[str, type[EntityBase]] = {\n")
    for e in manifest.entities:
        out.append(f'    "{e.name}": {e.name},\n')
    out.append("}\n")
    return "".join(out)


def _model_class(e: EntityDef) -> str:
    frozen = e.mutability is not Mutability.MUTABLE
    lines = [f"\n\nclass {e.name}(EntityBase):\n", f'    """{e.description}"""\n\n']
    lines.append(f'    model_config = ConfigDict(extra="forbid", frozen={frozen})\n')
    lines.append(f'    __entity__: ClassVar[str] = "{e.name}"\n')
    lines.append(f'    __table__: ClassVar[str] = "{e.table}"\n')
    if e.checks:
        checks = ", ".join(f"({c.id!r}, {c.py!r}, {c.description!r})" for c in e.checks)
        lines.append(f"    __checks__: ClassVar[tuple[tuple[str, str, str], ...]] = ({checks},)\n")
    lines.append("\n")
    required_first = sorted(e.all_fields, key=lambda f: 0 if (f.required and f.default is None) else 1)
    for f in required_first:
        typ = _py_type(f)
        constraints = []
        if f.min is not None:
            constraints.append(f"ge={_num(f.min)}")
        if f.max is not None:
            constraints.append(f"le={_num(f.max)}")
        if f.type is FieldType.ARRAY:
            constraints = []
        if f.required and f.default is None:
            if constraints:
                lines.append(f"    {f.name}: {typ} = Field({', '.join(constraints)})\n")
            else:
                lines.append(f"    {f.name}: {typ}\n")
        elif f.default is not None:
            default = _py_default(f)
            if constraints:
                lines.append(f"    {f.name}: {typ} = Field(default={default}, {', '.join(constraints)})\n")
            else:
                lines.append(f"    {f.name}: {typ} = {default}\n")
        else:
            if f.type is FieldType.ARRAY:
                lines.append(f"    {f.name}: {typ} = Field(default_factory=list)\n")
            elif constraints:
                lines.append(f"    {f.name}: {typ} | None = Field(default=None, {', '.join(constraints)})\n")
            else:
                lines.append(f"    {f.name}: {typ} | None = None\n")
    return "".join(lines)


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


SA_TYPES: dict[FieldType, str] = {
    FieldType.UUID: "Uuid",
    FieldType.TEXT: "Text",
    FieldType.INT: "Integer",
    FieldType.BIGINT: "BigInteger",
    FieldType.NUMERIC: "Numeric",
    FieldType.BOOL: "Boolean",
    FieldType.TIMESTAMP: "DateTime(timezone=True)",
    FieldType.DATE: "Date",
    FieldType.JSON: "JSONB",
    FieldType.REF: "Uuid",
}


def tables_module(manifest: Manifest) -> str:
    s = manifest.schema_name
    out = [
        header(manifest, "#"),
        '"""SQLAlchemy Core tables. Enum types are created by the migration (create_type=False)."""\n',
    ]
    out.append(
        "from __future__ import annotations\n\n"
        "from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, Table, Text, Uuid, text\n"  # noqa: E501
        "from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB\n\n"
        f'SCHEMA = "{s}"\n'
        "metadata = MetaData(schema=SCHEMA)\n\n\n"
        "def _enum(name: str, *values: str) -> ENUM:\n"
        "    return ENUM(*values, name=name, schema=SCHEMA, create_type=False)\n\n\n"
        "def _common() -> list[Column[object]]:\n"
        "    return [\n"
        '        Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),\n'
        '        Column("ontology_version", Text, nullable=False),\n'
        '        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),\n'
        "        Column(\"created_by\", Text, nullable=False, server_default=text(\"coalesce(current_setting('hai.actor', true), 'unknown')\")),\n"  # noqa: E501
        "    ]\n\n"
    )
    for code in sorted(manifest.vocabularies):
        voc = manifest.vocabularies[code]
        values = ", ".join(f'"{v.code}"' for v in voc.ordered_values)
        out.append(f'ENUM_{code.upper()} = _enum("{code}", {values})\n')
    out.append("\n")
    for e in manifest.entities:
        out.append(f'\n{e.table} = Table(\n    "{e.table}",\n    metadata,\n    *_common(),\n')
        for f in e.all_fields:
            out.append(f"    {_sa_column(f)},\n")
        out.append(")\n")
    out.append("\nTABLES: dict[str, Table] = {\n")
    for e in manifest.entities:
        out.append(f'    "{e.name}": {e.table},\n')
    out.append("}\n")
    return "".join(out)


def _sa_column(f: FieldDef) -> str:
    if f.type is FieldType.ENUM:
        assert f.vocabulary is not None
        typ = f"ENUM_{f.vocabulary.upper()}"
    elif f.type is FieldType.ARRAY:
        assert f.items is not None
        if f.items is FieldType.ENUM:
            assert f.vocabulary is not None
            typ = f"ARRAY(ENUM_{f.vocabulary.upper()})"
        else:
            typ = f"ARRAY({SA_TYPES[f.items]})"
    else:
        typ = SA_TYPES[f.type]
    parts = [f'Column("{f.name}", {typ}']
    if f.required:
        parts.append("nullable=False")
    if f.unique:
        parts.append("unique=True")
    if f.default is not None:
        if isinstance(f.default, bool):
            parts.append(f'server_default=text("{"true" if f.default else "false"}")')
        elif isinstance(f.default, int | float):
            parts.append(f'server_default=text("{f.default}")')
        else:
            parts.append(f"server_default=text(\"'{f.default}'\")")
    return ", ".join(parts) + ")"


def init_module(manifest: Manifest) -> str:
    return (
        header(manifest, "#")
        + '"""Generated code for hai-core. Services refuse to start if MANIFEST_HASH differs from the manifest."""\n\n'
        + "from hai_core.generated.enums import MANIFEST_HASH, METHODOLOGY_VERSION, ONTOLOGY_VERSION, RULESET_VERSION\n\n"  # noqa: E501
        + '__all__ = ["MANIFEST_HASH", "METHODOLOGY_VERSION", "ONTOLOGY_VERSION", "RULESET_VERSION"]\n'
    )

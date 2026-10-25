"""Run every generator deterministically; check for drift."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hai_ontology.codegen import docs_gen, jsonschema_gen, python_code, sql, typescript
from hai_ontology.codegen.common import Outputs
from hai_ontology.meta import Manifest

__all__ = ["GeneratedFile", "Outputs", "check", "generate", "render_all"]


@dataclass(frozen=True)
class GeneratedFile:
    path: Path
    content: str


def render_all(manifest: Manifest, root: Path) -> list[GeneratedFile]:
    out = Outputs(root)
    return [
        GeneratedFile(out.sql_baseline, sql.baseline(manifest)),
        GeneratedFile(out.python_dir / "__init__.py", python_code.init_module(manifest)),
        GeneratedFile(out.python_dir / "enums.py", python_code.enums_module(manifest)),
        GeneratedFile(out.python_dir / "models.py", python_code.models_module(manifest)),
        GeneratedFile(out.python_dir / "tables.py", python_code.tables_module(manifest)),
        GeneratedFile(out.schema_dir / "__init__.py", _schema_init(manifest)),
        GeneratedFile(
            out.schema_dir / "finding_schema.json",
            jsonschema_gen.render(jsonschema_gen.finding_schema(manifest)),
        ),
        GeneratedFile(
            out.schema_dir / "proposal_schema.json",
            jsonschema_gen.render(jsonschema_gen.proposal_schema(manifest)),
        ),
        GeneratedFile(out.typescript, typescript.typescript_module(manifest)),
        GeneratedFile(out.docs_dir / "labels.json", docs_gen.render_labels(manifest)),
        GeneratedFile(out.docs_dir / "glossary.md", docs_gen.glossary(manifest)),
        GeneratedFile(out.docs_dir / "hai-ontology.jsonld", docs_gen.render_jsonld(manifest)),
    ]


def _schema_init(manifest: Manifest) -> str:
    from hai_ontology.codegen.common import header

    return (
        header(manifest, "#")
        + '"""Generated JSON Schemas for LLM outputs (strict mode)."""\n\n'
        + "import json\nfrom pathlib import Path\nfrom typing import Any\n\n"
        + f'MANIFEST_HASH = "{manifest.hash}"\n'
        + "_HERE = Path(__file__).parent\n\n\n"
        + "def finding_schema() -> dict[str, Any]:\n"
        + '    data: dict[str, Any] = json.loads((_HERE / "finding_schema.json").read_text(encoding="utf-8"))\n'
        + "    return data\n\n\n"
        + "def proposal_schema() -> dict[str, Any]:\n"
        + '    data: dict[str, Any] = json.loads((_HERE / "proposal_schema.json").read_text(encoding="utf-8"))\n'
        + "    return data\n"
    )


def generate(manifest: Manifest, root: Path) -> list[Path]:
    written: list[Path] = []
    for gf in render_all(manifest, root):
        gf.path.parent.mkdir(parents=True, exist_ok=True)
        if not gf.path.exists() or gf.path.read_text(encoding="utf-8") != gf.content:
            gf.path.write_text(gf.content, encoding="utf-8")
            written.append(gf.path)
    return written


def check(manifest: Manifest, root: Path) -> list[Path]:
    """Paths whose on-disk content differs from what the manifest generates."""
    stale: list[Path] = []
    for gf in render_all(manifest, root):
        if not gf.path.exists() or gf.path.read_text(encoding="utf-8") != gf.content:
            stale.append(gf.path)
    return stale

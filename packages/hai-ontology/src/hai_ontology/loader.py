"""Load the manifest from a directory (or a git ref) and compute its hash."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from hai_ontology.meta import (
    DERIVED_VOCABULARIES,
    AttrType,
    CriterionFile,
    DecisionsFile,
    ExampleRecord,
    Manifest,
    MethodologyFile,
    OntologyFile,
    PillarsFile,
    RulesFile,
    VocabularyDef,
    VocabularyFile,
    VocabularyValue,
)

__all__ = [
    "ManifestLoadError",
    "canonical_json",
    "compute_hash",
    "find_ontology_dir",
    "find_repo_root",
    "load_manifest",
    "load_manifest_from_git",
    "manifest_hash",
]

ONTOLOGY_DIR_ENV = "HAI_ONTOLOGY_DIR"


class ManifestLoadError(Exception):
    """A manifest file is missing or does not match the meta-model."""


Reader = Callable[[str], str | None]
Lister = Callable[[str], list[str]]


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` until a directory containing ``ontology/ontology.yaml`` is found."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ontology" / "ontology.yaml").exists():
            return candidate
    raise ManifestLoadError(f"no ontology/ontology.yaml above {here}")


def find_ontology_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get(ONTOLOGY_DIR_ENV)
    if env:
        return Path(env).resolve()
    return find_repo_root() / "ontology"


def _fs_reader(root: Path) -> Reader:
    def read(rel: str) -> str | None:
        p = root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    return read


def _fs_lister(root: Path) -> Lister:
    def ls(rel: str) -> list[str]:
        d = root / rel
        if not d.exists():
            return []
        return sorted(str(p.relative_to(root)) for p in d.iterdir() if p.is_file())

    return ls


def load_manifest(ontology_dir: str | Path | None = None) -> Manifest:
    """Load and hash the manifest under ``ontology_dir`` (default: resolved from cwd)."""
    root = find_ontology_dir(ontology_dir)
    manifest = _load(_fs_reader(root), _fs_lister(root), source=str(root))
    manifest.source_dir = root
    return manifest


def load_manifest_from_git(ref: str, subdir: str = "ontology", repo: Path | None = None) -> Manifest | None:
    """Load the manifest as it was at ``ref``. Returns ``None`` if the ref has no ontology."""
    cwd = repo or find_repo_root()

    def git(*args: str) -> str | None:
        git_bin = shutil.which("git") or "/usr/bin/git"
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [git_bin, *args], cwd=cwd, capture_output=True, text=True, check=False
        )
        return proc.stdout if proc.returncode == 0 else None

    listing = git("ls-tree", "-r", "--name-only", ref, "--", subdir)
    if listing is None or not listing.strip():
        return None
    files = [line for line in listing.splitlines() if line.strip()]
    prefix = subdir.rstrip("/") + "/"

    def read(rel: str) -> str | None:
        return git("show", f"{ref}:{prefix}{rel}")

    def ls(rel: str) -> list[str]:
        want = prefix + rel.rstrip("/") + "/"
        return sorted(f[len(prefix) :] for f in files if f.startswith(want) and "/" not in f[len(want) :])

    return _load(read, ls, source=f"git:{ref}")


def _yaml(read: Reader, rel: str, source: str) -> Any:
    text = read(rel)
    if text is None:
        raise ManifestLoadError(f"{source}: missing {rel}")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"{source}: {rel}: {exc}") from exc


def _model(kind: type[Any], data: Any, where: str) -> Any:
    try:
        return kind.model_validate(data)
    except ValidationError as exc:
        lines = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ManifestLoadError(f"{where}: {lines}") from exc


def _load(read: Reader, ls: Lister, source: str) -> Manifest:
    ontology: OntologyFile = _model(OntologyFile, _yaml(read, "ontology.yaml", source), f"{source}/ontology.yaml")

    vocabularies: dict[str, VocabularyDef] = {}
    for rel in ls("vocabularies"):
        if not rel.endswith(".yaml"):
            continue
        vf: VocabularyFile = _model(VocabularyFile, _yaml(read, rel, source), f"{source}/{rel}")
        if vf.vocabulary.code in DERIVED_VOCABULARIES or vf.vocabulary.derived:
            raise ManifestLoadError(
                f"{source}/{rel}: {vf.vocabulary.code} is a derived vocabulary and must not be hand-written"
            )
        if vf.vocabulary.code in vocabularies:
            raise ManifestLoadError(f"{source}/{rel}: duplicate vocabulary {vf.vocabulary.code}")
        vocabularies[vf.vocabulary.code] = vf.vocabulary

    methodology: MethodologyFile = _model(
        MethodologyFile,
        _yaml(read, "methodology/methodology.yaml", source),
        f"{source}/methodology/methodology.yaml",
    )
    pillars: PillarsFile = _model(
        PillarsFile, _yaml(read, "methodology/pillars.yaml", source), f"{source}/methodology/pillars.yaml"
    )
    criteria = []
    for rel in ls("methodology/criteria"):
        if rel.endswith(".yaml"):
            cf: CriterionFile = _model(CriterionFile, _yaml(read, rel, source), f"{source}/{rel}")
            criteria.append(cf.criterion)
    criteria.sort(key=lambda c: (_pillar_order(pillars, c.pillar), c.code))
    rules: RulesFile = _model(
        RulesFile, _yaml(read, "methodology/rules.yaml", source), f"{source}/methodology/rules.yaml"
    )
    decisions: DecisionsFile = _model(
        DecisionsFile,
        _yaml(read, "methodology/decisions.yaml", source),
        f"{source}/methodology/decisions.yaml",
    )

    try:
        vocabularies["pillar_code"] = _derived_pillar_vocabulary(pillars)
        vocabularies["criterion_code"] = _derived_criterion_vocabulary(criteria)
    except ValidationError as exc:
        raise ManifestLoadError(f"{source}: derived vocabularies: {exc.errors()[0]['msg']}") from exc

    manifest = Manifest(
        ontology=ontology,
        vocabularies=dict(sorted(vocabularies.items())),
        methodology=methodology.methodology,
        pillars=sorted(pillars.pillars, key=lambda p: p.display_order),
        criteria=criteria,
        ruleset=rules.ruleset,
        decisions=decisions.decisions,
        examples_valid=_examples(read, ls, "examples/valid", source),
        examples_invalid=_examples(read, ls, "examples/invalid", source),
    )
    manifest.hash = compute_hash(manifest)
    return manifest


def _pillar_order(pillars: PillarsFile, code: str) -> int:
    for p in pillars.pillars:
        if p.code == code:
            return p.display_order
    return 999


def _examples(read: Reader, ls: Lister, rel: str, source: str) -> list[ExampleRecord]:
    out: list[ExampleRecord] = []
    for f in ls(rel):
        if not f.endswith(".json"):
            continue
        text = read(f)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestLoadError(f"{source}/{f}: {exc}") from exc
        data["path"] = f
        ex: ExampleRecord = _model(ExampleRecord, data, f"{source}/{f}")
        out.append(ex)
    return out


def _derived_pillar_vocabulary(pillars: PillarsFile) -> VocabularyDef:
    return VocabularyDef(
        code="pillar_code",
        title="Pillar code",
        description="The six pillars. Derived from methodology/pillars.yaml; never hand-written.",
        ordered=True,
        attributes={"legacy_id": AttrType.STRING, "weight": AttrType.NUMBER},
        values=[
            VocabularyValue(
                code=p.code,
                label=p.name,
                description=p.description,
                rank=p.display_order,
                aliases=[p.legacy_id],
                attributes={"legacy_id": p.legacy_id, "weight": p.weight},
            )
            for p in sorted(pillars.pillars, key=lambda p: p.display_order)
        ],
        derived=True,
    )


def _derived_criterion_vocabulary(criteria: Iterable[Any]) -> VocabularyDef:
    values = []
    for i, c in enumerate(criteria):
        values.append(
            VocabularyValue(
                code=c.code,
                label=c.name,
                description=c.definition,
                rank=i + 1,
                aliases=[c.legacy_id],
                attributes={
                    "pillar": c.pillar,
                    "legacy_id": c.legacy_id,
                    "materiality": c.materiality,
                    "materiality_weight": c.materiality_weight,
                    "weight": c.weight,
                    "freshness_window_months": c.freshness_window_months,
                },
            )
        )
    return VocabularyDef(
        code="criterion_code",
        title="Criterion code",
        description="The twenty criteria. Derived from methodology/criteria/*.yaml; never hand-written. Codes are permanent.",  # noqa: E501
        ordered=True,
        attributes={
            "pillar": AttrType.STRING,
            "legacy_id": AttrType.STRING,
            "materiality": AttrType.STRING,
            "materiality_weight": AttrType.NUMBER,
            "weight": AttrType.NUMBER,
            "freshness_window_months": AttrType.NUMBER,
        },
        values=values,
        derived=True,
    )


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_hash(manifest: Manifest) -> str:
    """SHA-256 over the canonical manifest content (everything except the hash and source path)."""
    payload = manifest.model_dump(mode="json", exclude={"hash", "source_dir"})
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def manifest_hash(ontology_dir: str | Path | None = None) -> str:
    return load_manifest(ontology_dir).hash

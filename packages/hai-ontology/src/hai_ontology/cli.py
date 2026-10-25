"""The ``hai-ontology`` command line.

validate, codegen [--check], diff, check-bump, migrate-plan, baseline, show,
export, bump. OLD and NEW arguments accept a directory or ``git:<ref>``.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

from hai_ontology import codegen
from hai_ontology.loader import ManifestLoadError, find_repo_root, load_manifest, load_manifest_from_git
from hai_ontology.meta import Manifest
from hai_ontology.validator import validate
from hai_ontology.versioning import ChangeLevel, bump, check_bump, diff, migrate_plan


def _load(spec: str | None) -> Manifest | None:
    if spec is None:
        return load_manifest()
    if spec.startswith("git:"):
        return load_manifest_from_git(spec[4:])
    return load_manifest(spec)


def _implementations(module_path: str | None) -> Mapping[str, str] | None:
    if not module_path:
        return None
    module = importlib.import_module(module_path)
    registry = getattr(module, "RULE_IMPLEMENTATIONS", None)
    if registry is None or not isinstance(registry, Mapping):
        raise SystemExit(f"{module_path} does not expose RULE_IMPLEMENTATIONS")
    return {str(k): str(v) for k, v in registry.items()}


def cmd_validate(args: argparse.Namespace) -> int:
    m = load_manifest(args.ontology)
    report = validate(m, _implementations(args.implementations))
    for issue in report.issues:
        print(str(issue))
    print(
        f"ontology {m.ontology_version}, methodology {m.methodology_version}, ruleset {m.ruleset.version}: "
        f"{len(m.entities)} entities, {len(m.vocabularies)} vocabularies, {len(m.criteria)} criteria, "
        f"{len(m.ruleset.rules)} rules; {len(report.errors)} error(s), {len(report.warnings)} warning(s); "
        f"hash {m.hash[:12]}"
    )
    if args.strict and report.warnings:
        return 1
    return 0 if report.ok else 1


def cmd_codegen(args: argparse.Namespace) -> int:
    m = load_manifest(args.ontology)
    root = Path(args.root) if args.root else find_repo_root(m.source_dir)
    if args.check:
        stale = codegen.check(m, root)
        if stale:
            for p in stale:
                print(f"stale: {p.relative_to(root)}")
            print(f"{len(stale)} generated file(s) are out of date; run hai-ontology codegen")
            return 1
        print(f"{len(codegen.render_all(m, root))} generated files are up to date")
        return 0
    written = codegen.generate(m, root)
    for p in written:
        print(f"wrote {p.relative_to(root)}")
    print(f"{len(written)} file(s) written, {len(codegen.render_all(m, root)) - len(written)} unchanged")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    old, new = _load(args.old), _load(args.new)
    if new is None:
        raise SystemExit(f"{args.new} has no ontology")
    changes = diff(old, new)
    for c in changes:
        print(f"{c.level.label:6} {c.scope:11} {c.path}: {c.description}")
    for scope in ("ontology", "methodology"):
        level = max((c.level for c in changes if c.scope == scope), default=ChangeLevel.NONE)
        print(f"required {scope} bump: {level.label}")
    return 0


def cmd_check_bump(args: argparse.Namespace) -> int:
    old, new = _load(args.old), _load(args.new)
    if new is None:
        raise SystemExit(f"{args.new} has no ontology")
    ok = True
    for r in check_bump(old, new):
        status = "ok" if r.ok else "FAIL"
        print(
            f"{status}: {r.scope} {r.old_version} -> {r.new_version} (required {r.required.label}, got {r.actual.label})"  # noqa: E501
        )
        if not r.ok or args.verbose:
            for n in r.notes:
                print(f"    {n}")
        ok = ok and r.ok
    return 0 if ok else 1


def cmd_migrate_plan(args: argparse.Namespace) -> int:
    old, new = _load(args.old), _load(args.new)
    if new is None:
        raise SystemExit(f"{args.new} has no ontology")
    try:
        plan = migrate_plan(old, new, allow_breaking=args.allow_breaking)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(plan, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(plan, end="")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from hai_ontology.codegen import sql

    m = load_manifest(args.ontology)
    text = sql.baseline(m)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    m = load_manifest(args.ontology)
    what = args.what
    if what is None:
        print(f"ontology {m.ontology_version} ({m.ontology.ontology.title})")
        print(f"methodology {m.methodology_version} ({m.methodology.status}), ruleset {m.ruleset.version}")
        print(f"manifest hash {m.hash}")
        print(f"entities: {', '.join(m.entity_names)}")
        print(f"vocabularies: {', '.join(sorted(m.vocabularies))}")
        print(f"criteria: {', '.join(c.code for c in m.criteria)}")
        return 0
    if what in m.vocabularies:
        print(yaml.safe_dump(m.vocabularies[what].model_dump(mode="json"), sort_keys=False))
        return 0
    if what in m.entity_names:
        print(yaml.safe_dump(m.entity(what).model_dump(mode="json"), sort_keys=False))
        return 0
    for c in m.criteria:
        if c.code == what or c.legacy_id == what:
            print(yaml.safe_dump(c.model_dump(mode="json"), sort_keys=False))
            return 0
    for r in m.ruleset.rules:
        if r.code == what:
            print(yaml.safe_dump(r.model_dump(mode="json"), sort_keys=False))
            return 0
    print(f"nothing named {what!r}", file=sys.stderr)
    return 1


def cmd_export(args: argparse.Namespace) -> int:
    from hai_ontology.codegen import docs_gen

    m = load_manifest(args.ontology)
    if args.format == "json":
        print(json.dumps(m.model_dump(mode="json", exclude={"source_dir"}), indent=2))
    elif args.format == "jsonld":
        print(docs_gen.render_jsonld(m), end="")
    else:
        print(docs_gen.render_labels(m), end="")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    m = load_manifest(args.ontology)
    assert m.source_dir is not None
    if args.scope == "ontology":
        path = m.source_dir / "ontology.yaml"
        old = m.ontology_version
    else:
        path = m.source_dir / "methodology" / "methodology.yaml"
        old = m.methodology_version
    new = bump(old, args.level)
    text = path.read_text(encoding="utf-8")
    needle = f"version: {old}"
    if text.count(needle) != 1:
        raise SystemExit(f"could not find a single 'version: {old}' in {path}")
    path.write_text(text.replace(needle, f"version: {new}", 1), encoding="utf-8")
    print(f"{args.scope} {old} -> {new} ({path})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hai-ontology", description="HAI ontology manifest tools")
    p.add_argument(
        "--ontology", help="path to the ontology directory (default: ontology/ above cwd or HAI_ONTOLOGY_DIR)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("validate", help="validate the manifest")
    s.add_argument("--implementations", help="module exposing RULE_IMPLEMENTATIONS, for example hai_engine.rules")
    s.add_argument("--strict", action="store_true", help="fail on warnings too")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("codegen", help="write the generated files")
    s.add_argument("--check", action="store_true", help="fail if generated files are stale")
    s.add_argument("--root", help="repository root (default: parent of the ontology directory)")
    s.set_defaults(func=cmd_codegen)

    for name, func, helptext in (
        ("diff", cmd_diff, "classify every change between two manifests"),
        ("check-bump", cmd_check_bump, "fail when the version did not move far enough"),
        ("migrate-plan", cmd_migrate_plan, "SQL for additive changes between two manifests"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("old", help="directory or git:<ref>")
        s.add_argument("new", help="directory or git:<ref>")
        if name == "check-bump":
            s.add_argument("--verbose", "-v", action="store_true")
        if name == "migrate-plan":
            s.add_argument("--allow-breaking", action="store_true")
            s.add_argument("--output", "-o")
        s.set_defaults(func=func)

    s = sub.add_parser("baseline", help="print or write the baseline SQL")
    s.add_argument("--output", "-o")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("show", help="show the manifest summary, an entity, a vocabulary, a criterion or a rule")
    s.add_argument("what", nargs="?")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("export", help="export the manifest")
    s.add_argument("--format", choices=["json", "jsonld", "labels"], default="json")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("bump", help="bump the ontology or methodology version in the YAML")
    s.add_argument("scope", choices=["ontology", "methodology"])
    s.add_argument("level", choices=["patch", "minor", "major"])
    s.set_defaults(func=cmd_bump)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except ManifestLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

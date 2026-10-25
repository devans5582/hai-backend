"""No criterion code or distinctive status string is hand-typed outside generated files.

The manifest is the only place these literals may live. Generated files, the
ontology YAML, migrations, docs, the legacy service and tests are allowed; the
hand-written source of every package, service and the frontend is not.
"""

from __future__ import annotations

import re
from pathlib import Path

from hai_ontology.loader import find_repo_root, load_manifest

REPO = find_repo_root(Path(__file__))

CRITERION_CODE = re.compile(r"[\"'`](?:TRU|ACC|PUR|SAF|TRN|IMP)-\d{2}[\"'`]")
# Distinctive vocabulary codes; common words such as "failed" or "missing" are not checked.
DISTINCTIVE = [
    "hai_certified",
    "completed_unverified",
    "awaiting_review",
    "certification_not_yet_achieved",
    "governance_baseline",
    "access_limited",
    "insufficient_evidence",
    "confidence_too_low",
    "not_applicable",
    "inadmissible_irrelevant",
    "inadmissible_stale",
    "inadmissible_unverifiable",
    "inadmissible_untrusted",
    "pending_review",
    "under_investigation",
    "closed_verified",
    "stated_commitment",
    "specified_control",
    "documented_execution",
    "independently_verified",
    "rate_limited",
]
STATUS_LITERAL = re.compile(r"[\"'`](?:" + "|".join(DISTINCTIVE) + r")[\"'`]")

SOURCE_DIRS = [
    "packages/hai-ontology/src",
    "packages/hai-core/src",
    "packages/hai-pipeline/src",
    "packages/hai-engine/src",
    "services/api/src",
    "services/worker/src",
    "frontend/src",
]
ALLOWED_PARTS = {"generated", "_generated", "tests", "test", "node_modules", "dist"}
ALLOWED_SUFFIXES = {".py", ".ts", ".tsx"}


def _source_files() -> list[Path]:
    out: list[Path] = []
    for d in SOURCE_DIRS:
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.suffix in ALLOWED_SUFFIXES and not (set(p.parts) & ALLOWED_PARTS) and ".test." not in p.name:
                out.append(p)
    return out


def test_no_hand_typed_codes_outside_generated_files() -> None:
    manifest = load_manifest(REPO / "ontology")
    assert manifest.criteria, "manifest loads"
    offenders: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "hai-codes: ok" in line:
                continue
            if CRITERION_CODE.search(line) or STATUS_LITERAL.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:100]}")
    assert offenders == [], "hand-typed codes found (import the generated enums instead):\n" + "\n".join(offenders)

"""Every acceptance test in the manifest names test functions that exist (AT-01 to AT-15)."""

from __future__ import annotations

import re
from pathlib import Path

from hai_ontology.meta import Manifest

REPO = Path(__file__).resolve().parent.parent
TEST_DIRS = ("tests", "packages", "services")


def _test_functions() -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"^(?:async )?def (test_\w+)\(", re.MULTILINE)
    for base in TEST_DIRS:
        for path in (REPO / base).rglob("test_*.py"):
            if "node_modules" in path.parts or "legacy" in path.parts:
                continue
            names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_acceptance_test_maps_to_a_test_function(manifest: Manifest) -> None:
    existing = _test_functions()
    assert manifest.ontology.acceptance_tests, "the manifest lists no acceptance tests"
    assert len(manifest.ontology.acceptance_tests) == 15
    missing = {(at.id, name) for at in manifest.ontology.acceptance_tests for name in at.tests if name not in existing}
    assert not missing, f"acceptance tests name functions that do not exist: {sorted(missing)}"
    assert all(at.tests for at in manifest.ontology.acceptance_tests)

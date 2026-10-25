"""The draft crosswalk file references only real criteria and declared frameworks, and stays marked draft
until Humaital approves it."""

from __future__ import annotations

from pathlib import Path

import yaml

from hai_ontology.meta import Manifest

CROSSWALKS = Path(__file__).resolve().parents[3] / "ontology" / "methodology" / "crosswalks.yaml"


def test_crosswalks_reference_real_criteria_and_frameworks(manifest: Manifest) -> None:
    data = yaml.safe_load(CROSSWALKS.read_text(encoding="utf-8"))["crosswalks"]
    frameworks = {f["code"] for f in data["frameworks"]}
    assert frameworks == {"EU_AI_ACT", "NIST_AI_RMF", "ISO_42001"}
    codes = {c.code for c in manifest.criteria}
    mapped: set[str] = set()
    for m in data["mappings"]:
        assert m["criterion"] in codes, m
        assert m["framework"] in frameworks, m
        assert m["direction"] in ("covers", "supports", "informs"), m
        assert m["clause"] and m["title"], m
        mapped.add(m["criterion"])
    assert mapped == codes, "every criterion has at least one mapping"


def test_crosswalks_are_marked_draft_until_approved() -> None:
    text = CROSSWALKS.read_text(encoding="utf-8")
    data = yaml.safe_load(text)["crosswalks"]
    if data["content_status"] == "draft":
        assert "TODO(humaital)" in text
    else:
        assert data["content_status"] == "approved" and "TODO(humaital)" not in text

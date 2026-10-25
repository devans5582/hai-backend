"""The safe expression language, lexicon terms and record validation."""

from __future__ import annotations

import pytest

from hai_ontology.conditions import UnsafeExpressionError, evaluate, parse
from hai_ontology.meta import Manifest
from hai_ontology.records import validate_record
from hai_ontology.terms import compile_term, find_terms, matches_any


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("stage_band == 'early' and size_band in ('small', 'mid')", True),
        ("stage_band != 'early'", False),
        ("not (ai_footprint > 0)", True),
        ("len(direct_urls) >= 1", True),
        ("nonblank(name)", True),
        ("nonblank(empty)", False),
        ("missing is None", True),
        ("missing > 3", False),
        ("level is not None and level >= 2", True),
    ],
)
def test_conditions(expr: str, expected: bool) -> None:
    ns = {
        "stage_band": "early",
        "size_band": "mid",
        "ai_footprint": 0,
        "direct_urls": ["x"],
        "name": "a",
        "empty": " ",
        "level": 3,
    }
    assert evaluate(expr, ns) is expected


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd')",
        "a.b == 1",
        "x + 1 > 2",
        "[i for i in range(3)]",
        "lambda: 1",
        "f'{x}'",
        "len(a, b)",
        "a if b else c",
        "x = 1",
    ],
)
def test_conditions_cannot_run_code(expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        parse(expr)


def test_term_regex_is_whole_word() -> None:
    assert matches_any("The company was sued last year", ["sued"])
    assert not matches_any("They pursued the matter", ["sued"])
    assert not matches_any("open the dashboard", ["board"])
    assert matches_any("the board approved it", ["board"])
    assert not matches_any("an impressive result", ["press"])
    assert matches_any("documented discrimination cases", ["discriminat*"])
    assert matches_any("Chief AI Officer Jane Doe", ["chief * officer"])
    assert matches_any(
        "Resolved 12 incidents reported in Q2 2025", ["\\d+\\s*(incidents|cases)\\s*(reported|resolved)"]
    )
    assert find_terms("AI, as we use it, is governed.", ["ai", "governed", "nope"]) == ["ai", "governed"]
    assert compile_term("data breach").search("a data  breach occurred")
    assert not compile_term("lawsuit").search("anti-lawsuit")


def test_validate_record_codes(manifest: Manifest) -> None:
    span = manifest.entity("EvidenceSpan")
    ok = {
        "source_document_id": "33333333-3333-4333-8333-333333333333",
        "char_start": 1,
        "char_end": 5,
        "quote": "abcd",
    }
    assert validate_record(manifest, span, ok) == []
    errs = {e.code for e in validate_record(manifest, span, {**ok, "char_end": 1})}
    assert "CK-SPAN-RANGE" in errs
    errs = {e.code for e in validate_record(manifest, span, {**ok, "quote": "  "})}
    assert "CK-SPAN-QUOTE" in errs
    errs = {e.code for e in validate_record(manifest, span, {**ok, "char_start": -1})}
    assert "E_RANGE" in errs
    errs = {e.code for e in validate_record(manifest, span, {**ok, "bogus": 1})}
    assert "E_UNKNOWN_FIELD" in errs
    errs = {e.code for e in validate_record(manifest, span, {**ok, "char_start": "one"})}
    assert "E_TYPE" in errs

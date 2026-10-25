"""Lexicon terms compile to whole-word regular expressions.

A term is matched as whole words so that "sued" never matches "pursued" and
"board" never matches "dashboard" (Phase 6 used substring matching). A ``*``
inside a term is a wildcard for zero or more word characters, so
``discriminat*`` matches "discriminate" and "discrimination" and
``chief * officer`` matches "chief AI officer". Terms that already contain
regular-expression syntax (``\\d``, ``(``, ``|``, ``[``) are treated as regular
expressions and wrapped in word boundaries as a whole.
"""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = ["compile_term", "compile_terms", "find_terms", "matches_any"]

_REGEX_HINT = re.compile(r"\\[dws]|[()|\[\]{}+?^$]")


@lru_cache(maxsize=4096)
def compile_term(term: str) -> re.Pattern[str]:
    """Compile one lexicon term to a case-insensitive whole-word pattern."""
    t = term.strip()
    if not t:
        raise re.error("empty term")
    if _REGEX_HINT.search(t):
        body = t
    else:
        parts = [re.escape(p) for p in t.split("*")]
        body = r"\w*".join(parts)
        body = re.sub(r"\\ ", r"\\s+", body)
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", re.IGNORECASE)


def compile_terms(terms: list[str]) -> list[re.Pattern[str]]:
    return [compile_term(t) for t in terms]


def matches_any(text: str, terms: list[str]) -> bool:
    return any(p.search(text) for p in compile_terms(terms))


def find_terms(text: str, terms: list[str]) -> list[str]:
    """Return the terms that match ``text``, in lexicon order."""
    return [t for t in terms if compile_term(t).search(text)]

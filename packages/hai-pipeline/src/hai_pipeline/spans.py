"""Candidate spans with exact offsets.

The invariant every span keeps is ``stored_text[start:end] == quote`` (IC-03).
Spans are paragraphs, split at sentence boundaries when a paragraph is long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from hai_pipeline.extraction import ExtractedDocument, find_dates

MAX_SPAN_CHARS = 700
MIN_SPAN_CHARS = 40
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass(frozen=True)
class SpanCandidate:
    char_start: int
    char_end: int
    quote: str
    section_heading: str | None = None
    asserted_dates: list[date] = field(default_factory=list)

    def verify(self, stored_text: str) -> bool:
        return stored_text[self.char_start : self.char_end] == self.quote


class SpanMismatch(ValueError):  # noqa: N818 - domain-named exception
    """The quote does not match the stored text at the offsets (IC-03)."""


def verify_span(stored_text: str, char_start: int, char_end: int, quote: str) -> bool:
    return 0 <= char_start < char_end <= len(stored_text) and stored_text[char_start:char_end] == quote


def make_span(stored_text: str, char_start: int, char_end: int, *, heading: str | None = None) -> SpanCandidate:
    if not (0 <= char_start < char_end <= len(stored_text)):
        raise SpanMismatch(f"offsets {char_start}:{char_end} are outside the text of length {len(stored_text)}")
    quote = stored_text[char_start:char_end]
    if not quote.strip():
        raise SpanMismatch("a span must carry non-empty quoted text (IC-06)")
    return SpanCandidate(char_start, char_end, quote, heading, find_dates(quote))


def split_spans(
    doc: ExtractedDocument, *, max_chars: int = MAX_SPAN_CHARS, min_chars: int = MIN_SPAN_CHARS
) -> list[SpanCandidate]:
    """Paragraph spans from an extracted document; long paragraphs are split at sentences."""
    text = doc.text
    out: list[SpanCandidate] = []
    pos = 0
    for para in text.split("\n\n"):
        start = text.index(para, pos) if para else pos
        pos = start + len(para)
        stripped = para.strip()
        if len(stripped) < min_chars:
            continue
        lead = len(para) - len(para.lstrip())
        p_start = start + lead
        p_end = p_start + len(stripped)
        heading = doc.heading_for(p_start)
        if len(stripped) <= max_chars:
            out.append(make_span(text, p_start, p_end, heading=heading))
            continue
        for s_start, s_end in _sentence_windows(stripped, max_chars):
            seg = stripped[s_start:s_end].strip()
            if len(seg) < min_chars:
                continue
            a = p_start + s_start + (len(stripped[s_start:s_end]) - len(stripped[s_start:s_end].lstrip()))
            out.append(make_span(text, a, a + len(seg), heading=heading))
    return out


def _sentence_windows(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Greedy windows of whole sentences up to ``max_chars``."""
    boundaries = [0, *[m.end() for m in _SENTENCE_END.finditer(text)], len(text)]
    windows: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(boundaries)):
        if boundaries[i] - start > max_chars and boundaries[i - 1] > start:
            windows.append((start, boundaries[i - 1]))
            start = boundaries[i - 1]
    if start < len(text):
        # a single overlong sentence is cut hard at max_chars pieces
        while len(text) - start > max_chars:
            cut = text.rfind(" ", start, start + max_chars)
            if cut <= start:
                cut = start + max_chars
            windows.append((start, cut))
            start = cut
        windows.append((start, len(text)))
    return windows

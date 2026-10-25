"""Text extraction from HTML and PDF with a versioned extractor.

HTML: drop chrome (script, style, nav, header, footer, aside, forms), keep
paragraph structure, record headings with their character offsets, the
canonical URL, the title and a published date when the page asserts one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

EXTRACTOR_VERSION = "hai-extract-1.0.0"

_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "select",
    "input",
)
_BLOCK_TAGS = {
    "p",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "td",
    "th",
    "blockquote",
    "pre",
    "figcaption",
    "dt",
    "dd",
    "div",
    "section",
    "article",
    "main",
    "tr",
    "ul",
    "ol",
    "table",
    "summary",
    "details",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_DATE_META = (
    "article:published_time",
    "article:modified_time",
    "og:updated_time",
    "datePublished",
    "dateModified",
    "date",
    "pubdate",
    "publishdate",
    "DC.date.issued",
    "dc.date",
    "sailthru.date",
    "parsely-pub-date",
)
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")

_DATE_PATTERNS = [
    re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b"),
    re.compile(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d\d)\b",
        re.IGNORECASE,
    ),
]
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


@dataclass(frozen=True)
class Heading:
    offset: int
    level: int
    text: str


@dataclass
class ExtractedDocument:
    text: str
    title: str | None = None
    canonical_url: str | None = None
    published_at: date | None = None
    language: str | None = None
    headings: list[Heading] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, anchor text)
    extractor_version: str = EXTRACTOR_VERSION
    content_type: str = "text/html"

    def heading_for(self, offset: int) -> str | None:
        """The nearest heading above ``offset``."""
        best: Heading | None = None
        for h in self.headings:
            if h.offset <= offset:
                best = h
            else:
                break
        return best.text if best else None


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    t = text.strip()
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for pat in _DATE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        g = m.groups()
        try:
            if pat is _DATE_PATTERNS[0]:
                return date(int(g[0]), int(g[1]), int(g[2]))
            if pat is _DATE_PATTERNS[1]:
                return date(int(g[2]), _MONTHS[g[1].lower()], int(g[0]))
            return date(int(g[2]), _MONTHS[g[0].lower()], int(g[1]))
        except (ValueError, KeyError):
            continue
    return None


def find_dates(text: str) -> list[date]:
    """Dates asserted in a passage, in order, without duplicates."""
    out: list[date] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            d = parse_date(m.group(0))
            if d and d not in out:
                out.append(d)
    return out


def extract_html(html: str | bytes, *, base_url: str | None = None) -> ExtractedDocument:
    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    tree = HTMLParser(raw)
    doc = ExtractedDocument(text="")
    title_node = tree.css_first("title")
    if title_node is not None:
        doc.title = _clean(title_node.text()) or None
    og_title = tree.css_first('meta[property="og:title"]')
    if doc.title is None and og_title is not None:
        doc.title = _clean(og_title.attributes.get("content") or "") or None
    canon = tree.css_first('link[rel="canonical"]')
    if canon is not None and canon.attributes.get("href"):
        doc.canonical_url = canon.attributes.get("href")
    elif base_url:
        doc.canonical_url = base_url
    html_node = tree.css_first("html")
    if html_node is not None and html_node.attributes.get("lang"):
        doc.language = (html_node.attributes.get("lang") or "")[:5].lower() or None
    doc.published_at = _published(tree)
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            doc.links.append((href, _clean(a.text())))
    tree.strip_tags(list(_DROP_TAGS))
    body = tree.body or tree.root
    if body is None:
        return doc
    pieces: list[str] = []
    headings: list[Heading] = []
    offset = 0

    def emit(text: str, *, heading_level: int | None = None) -> None:
        nonlocal offset
        cleaned = _clean(text)
        if not cleaned:
            return
        if heading_level is not None:
            headings.append(Heading(offset, heading_level, cleaned))
        pieces.append(cleaned)
        offset += len(cleaned) + 2  # "\n\n" separator

    _walk(body, emit)
    doc.text = _BLANKS.sub("\n\n", "\n\n".join(pieces)).strip()
    doc.headings = headings
    return doc


def _walk(node: Node, emit: object) -> None:
    """Depth-first: leaf blocks become paragraphs; headings are flagged."""
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            emit("".join(buffer))  # type: ignore[operator]
            buffer.clear()

    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            txt = child.text(deep=False)
            if txt and txt.strip():
                buffer.append(txt)
            continue
        if tag in ("br",):
            flush()
            continue
        if tag in _HEADING_TAGS:
            flush()
            emit(child.text(), heading_level=int(tag[1]))  # type: ignore[operator]
            continue
        if tag in _BLOCK_TAGS:
            flush()
            if _has_block_children(child):
                _walk(child, emit)
            else:
                emit(child.text())  # type: ignore[operator]
            continue
        txt = child.text()
        if txt and txt.strip():
            buffer.append(txt)
    flush()


def _has_block_children(node: Node) -> bool:
    return any(child.tag in _BLOCK_TAGS or child.tag in _HEADING_TAGS for child in node.iter())


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def _published(tree: HTMLParser) -> date | None:
    for name in _DATE_META:
        for attr in ("property", "name", "itemprop"):
            node = tree.css_first(f'meta[{attr}="{name}"]')
            if node is not None:
                d = parse_date(node.attributes.get("content"))
                if d:
                    return d
    t = tree.css_first("time[datetime]")
    if t is not None:
        d = parse_date(t.attributes.get("datetime"))
        if d:
            return d
    return None


def extract_pdf(data: bytes) -> ExtractedDocument:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(_clean_pdf(page.extract_text() or ""))
        except Exception:
            pages.append("")
    text = _BLANKS.sub("\n\n", "\n\n".join(p for p in pages if p)).strip()
    meta = reader.metadata
    title = None
    published = None
    if meta:
        title = (meta.title or None) if hasattr(meta, "title") else None
        raw = getattr(meta, "creation_date_raw", None) or getattr(meta, "modification_date_raw", None)
        if isinstance(raw, str) and raw.startswith("D:") and len(raw) >= 10:
            try:
                published = date(int(raw[2:6]), int(raw[6:8]), int(raw[8:10]))
            except ValueError:
                published = None
    return ExtractedDocument(text=text, title=title, published_at=published, content_type="application/pdf")


def _clean_pdf(text: str) -> str:
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    para: list[str] = []
    for ln in lines:
        if not ln:
            if para:
                out.append(" ".join(para))
                para = []
        else:
            para.append(ln)
    if para:
        out.append(" ".join(para))
    return "\n\n".join(out)


def extract(content: bytes, content_type: str, *, base_url: str | None = None) -> ExtractedDocument:
    ctype = (content_type or "").lower()
    if "pdf" in ctype or content[:5] == b"%PDF-":
        return extract_pdf(content)
    if "json" in ctype:
        return ExtractedDocument(text=content.decode("utf-8", errors="replace"), content_type="application/json")
    if "xml" in ctype and "html" not in ctype:
        return extract_html(content, base_url=base_url)
    if "text/plain" in ctype:
        text = content.decode("utf-8", errors="replace")
        return ExtractedDocument(text=_BLANKS.sub("\n\n", text).strip(), content_type="text/plain")
    return extract_html(content, base_url=base_url)

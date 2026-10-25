"""URL canonicalisation and registrable domains."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "ref",
    }
)

# Second-level public suffixes that need three labels for a registrable domain.
_TWO_LEVEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
        "com.au", "net.au", "org.au", "edu.au", "gov.au",
        "co.nz", "org.nz", "net.nz", "govt.nz",
        "co.jp", "or.jp", "ne.jp", "go.jp", "ac.jp",
        "co.in", "net.in", "org.in", "gov.in", "ac.in",
        "com.br", "net.br", "org.br", "gov.br",
        "co.za", "org.za", "gov.za",
        "com.sg", "edu.sg", "gov.sg",
        "com.hk", "org.hk", "gov.hk",
        "com.mx", "org.mx", "gob.mx",
        "com.cn", "net.cn", "org.cn", "gov.cn",
        "com.tr", "org.tr", "gov.tr",
        "co.kr", "or.kr", "go.kr",
        "com.ar", "com.co", "com.pe", "com.ph", "com.my", "com.tw", "com.ua", "com.vn",
    }
)  # fmt: skip


def canonical_url(url: str) -> str:
    """Lower-case scheme and host, drop default ports, fragments and tracking parameters,
    sort the query and strip a trailing slash (except for the root path)."""
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def hostname(url: str) -> str:
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    return (urlsplit(text).hostname or "").lower()


def registrable_domain(host_or_url: str) -> str:
    """``www.news.example.co.uk`` becomes ``example.co.uk``; ``sub.acme.com`` becomes ``acme.com``."""
    host = hostname(host_or_url) if "/" in host_or_url or "://" in host_or_url else host_or_url.strip().lower()
    host = host.rstrip(".")
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    suffix2 = ".".join(labels[-2:])
    if suffix2 in _TWO_LEVEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix2


def same_registrable_domain(a: str, b: str) -> bool:
    return registrable_domain(a) == registrable_domain(b) != ""


def is_subdomain_of(host: str, domain: str) -> bool:
    host, domain = host.lower().rstrip("."), domain.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)

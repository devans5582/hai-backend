"""Publisher classification and independence.

The publisher type comes from the domain; the source tier is looked up from the
publisher type (vocabulary attribute). Independence comes from the publisher
and organization relations, never from the tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from hai_core.generated.enums import Independence, PublisherType, SourceTier, attribute
from hai_pipeline.urls import hostname, is_subdomain_of, registrable_domain

REGULATOR_DOMAINS = (
    "sec.gov", "ftc.gov", "justice.gov", "cftc.gov", "fcc.gov", "cfpb.gov", "ec.europa.eu", "europa.eu",
    "ico.org.uk", "gov.uk", "cnil.fr", "edpb.europa.eu", "courtlistener.com", "uscourts.gov", "govinfo.gov",
    "federalregister.gov", "oaic.gov.au", "priv.gc.ca", "canada.ca", "bundesnetzagentur.de", "datatilsynet.no",
)  # fmt: skip
STANDARDS_DOMAINS = (
    "iso.org",
    "nist.gov",
    "iafcertsearch.org",
    "bsigroup.com",
    "ukas.com",
    "anab.org",
    "ieee.org",
    "etsi.org",
)
ACADEMIC_DOMAINS = (
    "semanticscholar.org",
    "arxiv.org",
    "doi.org",
    "acm.org",
    "springer.com",
    "nature.com",
    "ssrn.com",
    "researchgate.net",
    "openreview.net",
    "aclanthology.org",
    "ieeexplore.ieee.org",
)
AUDIT_DOMAINS = (
    "deloitte.com",
    "pwc.com",
    "ey.com",
    "kpmg.com",
    "bdo.com",
    "schellman.com",
    "a-lign.com",
    "coalfire.com",
    "trustarc.com",
)
SOCIAL_DOMAINS = (
    "twitter.com",
    "x.com",
    "facebook.com",
    "linkedin.com",
    "reddit.com",
    "medium.com",
    "substack.com",
    "youtube.com",
    "tiktok.com",
    "news.ycombinator.com",
    "wikipedia.org",
    "wikidata.org",
)
REPO_DOMAINS = ("github.com", "gitlab.com", "bitbucket.org", "huggingface.co")
ARCHIVE_DOMAINS = ("web.archive.org", "archive.org")


@dataclass(frozen=True)
class PublisherInfo:
    name: str
    domain: str
    publisher_type: PublisherType
    is_organization: bool


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(is_subdomain_of(host, d) for d in domains)


def classify_publisher(
    url: str,
    *,
    org_domain: str,
    affiliate_domains: frozenset[str] = frozenset(),
    default: PublisherType = PublisherType.PRESS,
    name_hint: str | None = None,
) -> PublisherInfo:
    host = hostname(url)
    reg = registrable_domain(host)
    is_org = registrable_domain(org_domain) == reg or any(registrable_domain(a) == reg for a in affiliate_domains)
    if _matches(host, ARCHIVE_DOMAINS):
        ptype = PublisherType.ARCHIVE
    elif is_org:
        ptype = PublisherType.ORG_DISCLOSURE
    elif _matches(host, REGULATOR_DOMAINS) or host.endswith(".gov"):
        ptype = PublisherType.REGULATOR_RECORD
    elif _matches(host, STANDARDS_DOMAINS):
        ptype = PublisherType.STANDARDS_REGISTRY
    elif _matches(host, ACADEMIC_DOMAINS) or host.endswith((".edu", ".ac.uk")):
        ptype = PublisherType.ACADEMIC_RESEARCH
    elif _matches(host, AUDIT_DOMAINS):
        ptype = PublisherType.INDEPENDENT_AUDIT
    elif _matches(host, REPO_DOMAINS):
        ptype = PublisherType.ORG_REPOSITORY
    elif _matches(host, SOCIAL_DOMAINS):
        ptype = PublisherType.AGGREGATOR_OR_SOCIAL
    else:
        ptype = default
    return PublisherInfo(
        name=name_hint or reg or host, domain=reg or host, publisher_type=ptype, is_organization=is_org
    )


def source_tier_for(publisher_type: PublisherType) -> SourceTier:
    return SourceTier(str(attribute("publisher_type", publisher_type.value, "source_tier")))


def independence_for(
    publisher_type: PublisherType,
    *,
    publisher_is_org: bool,
    publisher_is_affiliate: bool = False,
    archived_publisher_is_org: bool | None = None,
) -> Independence:
    """Who stands behind the statement relative to the rated organization."""
    if publisher_type is PublisherType.ARCHIVE:
        if archived_publisher_is_org is None or archived_publisher_is_org:
            return Independence.SELF
        return Independence.INDEPENDENT
    if publisher_is_org:
        return Independence.SELF
    if publisher_is_affiliate:
        return Independence.AFFILIATE
    default = str(attribute("publisher_type", publisher_type.value, "default_independence"))
    return Independence(default)

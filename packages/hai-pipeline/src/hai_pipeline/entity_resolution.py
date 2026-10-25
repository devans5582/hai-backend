"""Entity resolution before collection.

Wikidata (official website P856, SEC CIK P5531, LEI P1278, industry P452,
parent P749, GitHub P2037), GLEIF and the SEC company tickers file. Identifiers
are marked verified only when the official website's registrable domain equals
the submitted domain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from hai_pipeline.http import Fetcher
from hai_pipeline.urls import registrable_domain

WIKIDATA_SEARCH = (
    "https://www.wikidata.org/w/api.php?action=wbsearchentities&search={q}&language=en&type=item&limit=5&format=json"
)
WIKIDATA_ENTITY = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids={id}&props=claims|labels|descriptions&languages=en&format=json"
GLEIF_SEARCH = "https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={q}&page[size]=5"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

P_WEBSITE = "P856"
P_CIK = "P5531"
P_LEI = "P1278"
P_INDUSTRY = "P452"
P_PARENT = "P749"
P_GITHUB = "P2037"

ORG_TERMS = (
    "company",
    "corporation",
    "organisation",
    "organization",
    "agency",
    "enterprise",
    "firm",
    "business",
    "bank",
    "manufacturer",
    "nonprofit",
    "university",
    "government",
)
_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|plc|co|company|the|holdings|group|ag|sa|nv|gmbh)\b\.?",
    re.IGNORECASE,
)


@dataclass
class EntityProfile:
    input_name: str
    input_domain: str
    resolved_name: str
    wikidata_qid: str | None = None
    official_website: str | None = None
    cik: str | None = None
    lei: str | None = None
    industry_qid: str | None = None
    parent_qid: str | None = None
    github_handle: str | None = None
    domain_verified: bool = False
    name_match: float = 0.0
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def verified_identifiers(self) -> dict[str, str]:
        """Identifiers safe to store: only when the official website matched the submitted domain."""
        if not self.domain_verified:
            return {}
        out: dict[str, str] = {}
        for key in ("wikidata_qid", "cik", "lei", "github_handle"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out


def normalise_name(name: str) -> str:
    n = _SUFFIX.sub(" ", name.lower())
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def name_match_score(a: str, b: str) -> float:
    """1.0 for the same normalised name; Jaccard over tokens otherwise (Phase 6 entity-resolver.js:204-217)."""
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / len(ta | tb), 2)


def _claim_value(claims: dict[str, Any], prop: str) -> Any:
    items = claims.get(prop) or []
    for item in items:
        snak = item.get("mainsnak", {})
        value = snak.get("datavalue", {}).get("value")
        if value is not None:
            return value
    return None


def _claim_string(claims: dict[str, Any], prop: str) -> str | None:
    v = _claim_value(claims, prop)
    return v if isinstance(v, str) else None


def _claim_item(claims: dict[str, Any], prop: str) -> str | None:
    v = _claim_value(claims, prop)
    if isinstance(v, dict) and "id" in v:
        return str(v["id"])
    return None


class EntityResolver:
    def __init__(self, fetcher: Fetcher, *, sec_tickers_url: str = SEC_TICKERS) -> None:
        self.fetcher = fetcher
        self.sec_tickers_url = sec_tickers_url

    async def resolve(self, name: str, domain: str) -> EntityProfile:
        profile = EntityProfile(input_name=name, input_domain=registrable_domain(domain), resolved_name=name)
        await self._wikidata(profile)
        if profile.official_website:
            profile.domain_verified = registrable_domain(profile.official_website) == profile.input_domain
            if not profile.domain_verified:
                profile.warnings.append(
                    f"official website {profile.official_website} does not match submitted domain {profile.input_domain}; "  # noqa: E501
                    "identifiers are not stored"
                )
        else:
            profile.warnings.append("no official website found for the resolved entity; identifiers are not stored")
        await self._gleif(profile)
        await self._sec(profile)
        profile.confidence = self._confidence(profile)
        return profile

    async def _wikidata(self, profile: EntityProfile) -> None:
        from urllib.parse import quote

        result, data = await self.fetcher.get_json(WIKIDATA_SEARCH.format(q=quote(profile.input_name)))
        if not isinstance(data, dict):
            profile.warnings.append(f"wikidata search {result.outcome}")
            return
        candidates = [
            c for c in data.get("search", []) if any(t in str(c.get("description", "")).lower() for t in ORG_TERMS)
        ] or list(data.get("search", []))
        if not candidates:
            profile.warnings.append("no Wikidata candidate")
            return
        best = max(candidates, key=lambda c: name_match_score(profile.input_name, str(c.get("label", ""))))
        qid = str(best["id"])
        _, entity = await self.fetcher.get_json(WIKIDATA_ENTITY.format(id=qid))
        if not isinstance(entity, dict):
            return
        ent = entity.get("entities", {}).get(qid, {})
        claims = ent.get("claims", {})
        label = ent.get("labels", {}).get("en", {}).get("value") or str(best.get("label", profile.input_name))
        profile.sources.append("wikidata")
        profile.wikidata_qid = qid
        profile.name_match = name_match_score(profile.input_name, label)
        if profile.name_match >= 0.6:
            profile.resolved_name = label
        else:
            profile.warnings.append(f"low name similarity to Wikidata entity {label!r}")
        profile.official_website = _claim_string(claims, P_WEBSITE)
        profile.cik = _claim_string(claims, P_CIK)
        profile.lei = _claim_string(claims, P_LEI)
        profile.industry_qid = _claim_item(claims, P_INDUSTRY)
        profile.parent_qid = _claim_item(claims, P_PARENT)
        profile.github_handle = _claim_string(claims, P_GITHUB)

    async def _gleif(self, profile: EntityProfile) -> None:
        from urllib.parse import quote

        if profile.lei:
            return
        _, data = await self.fetcher.get_json(GLEIF_SEARCH.format(q=quote(profile.resolved_name)))
        if not isinstance(data, dict):
            return
        for rec in data.get("data", []):
            attrs = rec.get("attributes", {})
            legal = attrs.get("entity", {}).get("legalName", {}).get("name", "")
            if name_match_score(profile.resolved_name, legal) >= 0.8:
                profile.lei = str(attrs.get("lei") or rec.get("id") or "") or None
                if profile.lei:
                    profile.sources.append("gleif")
                return

    async def _sec(self, profile: EntityProfile) -> None:
        if profile.cik:
            return
        _, data = await self.fetcher.get_json(self.sec_tickers_url)
        if not isinstance(data, dict):
            return
        rows = data.values() if all(isinstance(v, dict) for v in data.values()) else []
        target = normalise_name(profile.resolved_name)
        for row in rows:
            title = str(row.get("title", ""))
            if normalise_name(title) == target or name_match_score(profile.resolved_name, title) >= 0.9:
                profile.cik = str(row.get("cik_str", "")).zfill(10)
                profile.sources.append("sec_tickers")
                return

    @staticmethod
    def _confidence(profile: EntityProfile) -> float:
        """Phase 6 weights: name up to 0.35, domain up to 0.40, independent registry cross-check 0.25."""
        score = 0.0
        if profile.name_match >= 0.9:
            score += 0.35
        elif profile.name_match >= 0.7:
            score += 0.20
        elif profile.name_match >= 0.5:
            score += 0.10
        if profile.domain_verified:
            score += 0.40
        if profile.cik or profile.lei:
            score += 0.25
        return round(min(1.0, score), 2)

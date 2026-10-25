"""Evidence packs: one per criterion, built only from that criterion's links in the snapshot.

Ranked, size-limited, with omissions counted so they feed uncertainty (AT-09).
Inadmissible links never enter a pack; they are counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hai_core.generated.enums import RANKS, attribute
from hai_ontology.meta import CriterionDef

DEFAULT_MAX_ITEMS = 12
DEFAULT_MAX_CHARS = 7000


@dataclass(frozen=True)
class PackItem:
    link_id: str
    span_id: str
    quote: str
    polarity: str
    maturity_rung: str
    execution_level: str
    evidence_class: str
    independence: str
    source_tier: str
    publisher_type: str
    publisher_name: str | None
    published_at: str | None
    canonical_url: str | None
    document_title: str | None
    section_heading: str | None
    cluster_id: str | None
    document_id: str
    char_start: int
    char_end: int
    quote_sha256: str
    certificate_valid_until: str | None = None

    def for_model(self) -> dict[str, Any]:
        """What the model sees: data only, never instructions."""
        return {
            "link_id": self.link_id,
            "polarity": self.polarity,
            "quote": self.quote,
            "maturity_rung": self.maturity_rung,
            "execution_level": self.execution_level,
            "evidence_class": self.evidence_class,
            "independence": self.independence,
            "source_tier": self.source_tier,
            "publisher": self.publisher_name,
            "publisher_type": self.publisher_type,
            "published_at": self.published_at,
            "source_url": self.canonical_url,
            "section": self.section_heading,
        }


@dataclass
class EvidencePack:
    criterion: CriterionDef
    supporting: list[PackItem] = field(default_factory=list)
    contradicting: list[PackItem] = field(default_factory=list)
    neutral: list[PackItem] = field(default_factory=list)
    omitted: int = 0
    inadmissible: int = 0
    total_links: int = 0
    connector_runs: dict[str, Any] = field(default_factory=dict)

    @property
    def shown_ids(self) -> set[str]:
        return {i.link_id for i in (*self.supporting, *self.contradicting, *self.neutral)}

    @property
    def supporting_ids(self) -> set[str]:
        return {i.link_id for i in self.supporting}

    @property
    def contradicting_ids(self) -> set[str]:
        return {i.link_id for i in self.contradicting}

    @property
    def is_empty(self) -> bool:
        return not self.supporting and not self.contradicting

    def best_rung_rank(self) -> int:
        ranks = RANKS["maturity_rung"]
        return max((ranks[i.maturity_rung] for i in self.supporting), default=0)

    def item(self, link_id: str) -> PackItem | None:
        for i in (*self.supporting, *self.contradicting, *self.neutral):
            if i.link_id == link_id:
                return i
        return None

    def for_model(self) -> dict[str, Any]:
        return {
            "criterion": {
                "code": self.criterion.code,
                "name": self.criterion.name,
                "definition": self.criterion.definition,
                "levels": [
                    {
                        "level": lv.level,
                        "required_maturity_rung": lv.required_maturity_rung,
                        "descriptor": lv.descriptor,
                    }
                    for lv in sorted(self.criterion.levels, key=lambda x: x.level)
                ],
            },
            "supporting_evidence": [i.for_model() for i in self.supporting],
            "contradicting_evidence": [i.for_model() for i in self.contradicting],
            "omitted_evidence_count": self.omitted,
            "inadmissible_evidence_count": self.inadmissible,
        }


def _item(link_id: str, st: dict[str, Any]) -> PackItem:
    return PackItem(
        link_id=link_id,
        span_id=str(st["span_id"]),
        quote=str(st["quote"]),
        polarity=str(st["polarity"]),
        maturity_rung=str(st["maturity_rung"]),
        execution_level=str(st["execution_level"]),
        evidence_class=str(st["evidence_class"]),
        independence=str(st["independence"]),
        source_tier=str(st["source_tier"]),
        publisher_type=str(st["publisher_type"]),
        publisher_name=st.get("publisher_name"),
        published_at=st.get("published_at"),
        canonical_url=st.get("canonical_url"),
        document_title=st.get("document_title"),
        section_heading=st.get("section_heading"),
        cluster_id=st.get("cluster_id"),
        document_id=str(st["document_id"]),
        char_start=int(st["char_start"]),
        char_end=int(st["char_end"]),
        quote_sha256=str(st["quote_sha256"]),
        certificate_valid_until=st.get("certificate_valid_until"),
    )


def _rank_key(item: PackItem) -> tuple[int, float, float, str]:
    rung = RANKS["maturity_rung"].get(item.maturity_rung, 0)
    tier = float(attribute("source_tier", item.source_tier, "weight"))
    recency = item.published_at or ""
    return (
        -rung,
        -tier,
        -(float(len(item.quote)) / 1000.0),
        "~" if not recency else "".join(chr(255 - ord(c)) for c in recency),
    )


def build_pack(
    criterion: CriterionDef,
    link_states: dict[str, dict[str, Any]],
    *,
    connector_runs: dict[str, Any] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> EvidencePack:
    pack = EvidencePack(criterion=criterion, connector_runs=dict(connector_runs or {}))
    supporting: list[PackItem] = []
    contradicting: list[PackItem] = []
    neutral: list[PackItem] = []
    for link_id, st in link_states.items():
        if st.get("criterion_code") != criterion.code:
            continue  # a link contributes only to the criterion it names (IC-08)
        pack.total_links += 1
        if st.get("admissibility") != "admissible":
            pack.inadmissible += 1
            continue
        item = _item(link_id, st)
        if item.polarity == "supports":
            supporting.append(item)
        elif item.polarity == "contradicts":
            contradicting.append(item)
        else:
            neutral.append(item)
    supporting.sort(key=_rank_key)
    contradicting.sort(key=_rank_key)
    # Clusters count once: keep the best item per cluster among supporting links.
    seen_clusters: set[str] = set()
    deduped: list[PackItem] = []
    for item in supporting:
        if item.cluster_id and item.cluster_id in seen_clusters:
            pack.omitted += 1
            continue
        if item.cluster_id:
            seen_clusters.add(item.cluster_id)
        deduped.append(item)
    budget = max_chars
    for item in deduped:
        if len(pack.supporting) >= max_items or budget - len(item.quote) < 0:
            pack.omitted += 1
            continue
        budget -= len(item.quote)
        pack.supporting.append(item)
    for item in contradicting:
        if len(pack.contradicting) >= max(1, max_items // 2) or budget - len(item.quote) < 0:
            pack.omitted += 1
            continue
        budget -= len(item.quote)
        pack.contradicting.append(item)
    pack.neutral = neutral[:3]
    return pack


def build_all_packs(
    criteria: list[CriterionDef], link_states: dict[str, dict[str, Any]], connector_runs: dict[str, Any] | None = None
) -> dict[str, EvidencePack]:
    return {c.code: build_pack(c, link_states, connector_runs=connector_runs) for c in criteria}

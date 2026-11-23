"""Meta-model of the HAI manifest.

Strict Pydantic models (``extra="forbid"``) describing what the YAML under
``ontology/`` may contain: entities and fields, mutability, writer roles, the
relationship catalogue, vocabularies, integrity constraints, acceptance tests
and the full methodology. The loader builds a :class:`Manifest` from these.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool
AttrValue = str | int | float | bool | list[str]

# Columns every table carries. They are generated and never listed in YAML.
COMMON_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("id", "uuid", "Row id."),
    ("ontology_version", "text", "Ontology version the row was written under."),
    ("created_at", "timestamp", "When the row was written."),
    ("created_by", "text", "Principal that wrote the row (hai.actor)."),
)
COMMON_FIELD_NAMES = frozenset(name for name, _, _ in COMMON_FIELDS)
SUPERSEDES_FIELD = "supersedes_id"
DERIVED_VOCABULARIES: tuple[str, ...] = ("criterion_code", "pillar_code")


class Strict(BaseModel):
    """Base for every manifest model: unknown keys fail loudly, values are frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --------------------------------------------------------------------------- ontology


class FieldType(StrEnum):
    UUID = "uuid"
    TEXT = "text"
    INT = "int"
    BIGINT = "bigint"
    NUMERIC = "numeric"
    BOOL = "bool"
    TIMESTAMP = "timestamp"
    DATE = "date"
    JSON = "json"
    ENUM = "enum"
    REF = "ref"
    ARRAY = "array"


ARRAY_ITEM_TYPES = frozenset({FieldType.TEXT, FieldType.UUID, FieldType.ENUM, FieldType.DATE, FieldType.INT})


class FieldDef(Strict):
    name: str
    type: FieldType
    description: str
    required: bool = False
    immutable: bool = False
    unique: bool = False
    default: Scalar | None = None
    vocabulary: str | None = None
    ref: str | None = None
    items: FieldType | None = None
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _shape(self) -> FieldDef:
        if self.name in COMMON_FIELD_NAMES:
            raise ValueError(f"field {self.name!r} is a common field and must not be declared")
        if self.type is FieldType.ENUM and not self.vocabulary:
            raise ValueError(f"enum field {self.name!r} needs a vocabulary")
        if self.type is FieldType.REF and not self.ref:
            raise ValueError(f"ref field {self.name!r} needs a ref entity")
        if self.type is FieldType.ARRAY:
            if self.items not in ARRAY_ITEM_TYPES:
                raise ValueError(f"array field {self.name!r} needs items in {sorted(ARRAY_ITEM_TYPES)}")
            if self.items is FieldType.ENUM and not self.vocabulary:
                raise ValueError(f"array of enum field {self.name!r} needs a vocabulary")
        if self.type is not FieldType.ARRAY and self.items is not None:
            raise ValueError(f"field {self.name!r} is not an array but declares items")
        if self.vocabulary and self.type is not FieldType.ENUM and self.items is not FieldType.ENUM:
            raise ValueError(f"field {self.name!r} declares a vocabulary but is not an enum")
        if self.ref and self.type is not FieldType.REF:
            raise ValueError(f"field {self.name!r} declares a ref but is not a ref")
        return self


class CheckDef(Strict):
    """A declarative integrity check. ``sql`` becomes a CHECK constraint; ``py`` is the
    same predicate in the safe expression language, used by the Pydantic models."""

    id: str
    sql: str
    py: str
    description: str


class Mutability(StrEnum):
    MUTABLE = "mutable"
    APPEND_ONLY = "append_only"
    IMMUTABLE = "immutable"


class Layer(StrEnum):
    SUBJECT = "subject"
    EVIDENCE = "evidence"
    METHODOLOGY = "methodology"
    ASSESSMENT = "assessment"


class TransitionDef(Strict):
    field: str
    vocabulary: str


class EntityDef(Strict):
    name: str
    table: str
    layer: Layer
    mutability: Mutability
    writers: list[str]
    description: str
    fields: list[FieldDef]
    checks: list[CheckDef] = []
    unique: list[list[str]] = []
    transitions: TransitionDef | None = None
    supersedable: bool = False

    @model_validator(mode="after")
    def _unique_field_names(self) -> EntityDef:
        names = [f.name for f in self.fields]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"entity {self.name}: duplicate fields {sorted(dupes)}")
        if self.supersedable and SUPERSEDES_FIELD in names:
            raise ValueError(f"entity {self.name}: supersedes_id is added automatically")
        return self

    @property
    def all_fields(self) -> list[FieldDef]:
        """Declared fields plus ``supersedes_id`` when the entity is supersedable."""
        fields = list(self.fields)
        if self.supersedable:
            fields.append(
                FieldDef(
                    name=SUPERSEDES_FIELD,
                    type=FieldType.REF,
                    ref=self.name,
                    description="The row this one corrects or replaces.",
                )
            )
        return fields

    @property
    def field_map(self) -> dict[str, FieldDef]:
        return {f.name: f for f in self.all_fields}

    @property
    def insert_only(self) -> bool:
        return self.mutability is not Mutability.MUTABLE

    @property
    def immutable_fields(self) -> list[str]:
        if self.mutability is Mutability.IMMUTABLE:
            return [f.name for f in self.all_fields]
        return [f.name for f in self.all_fields if f.immutable]


class Cardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class FKDef(Strict):
    entity: str
    field: str
    to: str


class PolymorphicDef(Strict):
    entity: str
    type_field: str
    id_field: str


class ArrayRefDef(Strict):
    entity: str
    field: str
    to: str


class RelationDef(Strict):
    name: str
    from_entity: str = Field(alias="from")
    to: list[str]
    cardinality: Cardinality
    time_bound: bool
    description: str
    via: str | None = None
    fks: list[FKDef] = []
    polymorphic: PolymorphicDef | None = None
    array_field: ArrayRefDef | None = None


class EnforcedIn(StrEnum):
    DB_TRIGGER = "db_trigger"
    DB_CHECK = "db_check"
    DB_UNIQUE = "db_unique"
    DB_NOT_NULL = "db_not_null"
    DB_GRANTS = "db_grants"
    DB_RLS = "db_rls"
    VALIDATOR = "validator"
    RULES_ENGINE = "rules_engine"
    API = "api"
    REPORT_GENERATOR = "report_generator"
    EVALUATION_WORKER = "evaluation_worker"


class ICDef(Strict):
    id: str
    rule: str
    enforced_in: EnforcedIn
    implementation: str
    acceptance_test: str


class ATDef(Strict):
    id: str
    title: str
    description: str
    tests: list[str]


class LayerDef(Strict):
    code: Layer
    title: str
    description: str


class RoleDef(Strict):
    code: str
    description: str


class OntologyHeader(Strict):
    name: str
    version: str
    title: str
    description: str
    spec: str
    schema_name: str = Field(alias="schema")


class OntologyFile(Strict):
    ontology: OntologyHeader
    layers: list[LayerDef]
    roles: list[RoleDef]
    entities: list[EntityDef]
    relations: list[RelationDef]
    integrity_constraints: list[ICDef]
    acceptance_tests: list[ATDef]


# ----------------------------------------------------------------------- vocabularies


class AttrType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    LIST = "list"


class VocabularyValue(Strict):
    code: str
    label: str
    description: str = ""
    rank: int | None = None
    aliases: list[str] = []
    attributes: dict[str, AttrValue] = {}


class VocabularyDef(Strict):
    code: str
    title: str
    description: str
    values: list[VocabularyValue]
    ordered: bool = False
    attributes: dict[str, AttrType] = {}
    transitions: dict[str, list[str]] | None = None
    derived: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> VocabularyDef:
        codes = [v.code for v in self.values]
        if len(set(codes)) != len(codes):
            raise ValueError(f"vocabulary {self.code}: duplicate value codes")
        if self.ordered:
            ranks = [v.rank for v in self.values]
            if any(r is None for r in ranks) or len(set(ranks)) != len(ranks):
                raise ValueError(f"vocabulary {self.code}: ordered vocabularies need unique ranks on every value")
        for v in self.values:
            for key, val in v.attributes.items():
                if key not in self.attributes:
                    raise ValueError(f"vocabulary {self.code}: value {v.code} has undeclared attribute {key!r}")
                expected = self.attributes[key]
                ok = (
                    (expected is AttrType.STRING and isinstance(val, str))
                    or (expected is AttrType.NUMBER and isinstance(val, int | float) and not isinstance(val, bool))
                    or (expected is AttrType.BOOLEAN and isinstance(val, bool))
                    or (expected is AttrType.LIST and isinstance(val, list))
                )
                if not ok:
                    raise ValueError(f"vocabulary {self.code}: value {v.code} attribute {key!r} is not a {expected}")
        if self.transitions is not None:
            for src, dests in self.transitions.items():
                if src not in codes:
                    raise ValueError(f"vocabulary {self.code}: transition source {src!r} is not a value")
                for d in dests:
                    if d not in codes:
                        raise ValueError(f"vocabulary {self.code}: transition target {d!r} is not a value")
        return self

    @property
    def codes(self) -> list[str]:
        return [v.code for v in self.values]

    @property
    def ordered_values(self) -> list[VocabularyValue]:
        if self.ordered:
            return sorted(self.values, key=lambda v: v.rank or 0)
        return list(self.values)

    def value(self, code: str) -> VocabularyValue:
        for v in self.values:
            if v.code == code:
                return v
        raise KeyError(f"{self.code}.{code}")

    def attribute(self, code: str, key: str) -> AttrValue:
        return self.value(code).attributes[key]

    def resolve_alias(self, text: str) -> str | None:
        """Return the code for a value code or alias, case-insensitively."""
        needle = text.strip().lower()
        for v in self.values:
            if v.code.lower() == needle or needle in (a.lower() for a in v.aliases):
                return v.code
        return None


class VocabularyFile(Strict):
    vocabulary: VocabularyDef


# ------------------------------------------------------------------------ methodology


class Product(Strict):
    report_name: str
    long_name: str
    code_name: str


class LowConfidenceCap(Strict):
    confidence_below: float
    cap: float


class PillarWeightProfiles(Strict):
    """Pillar weights per stage band (decision D11). ``fixed`` uses pillars.yaml for everyone."""

    mode: Literal["fixed", "stage_profile"] = "fixed"
    content_status: str = "draft"
    profiles: dict[str, dict[str, float]] = {}

    def weights_for(self, stage_band: str, default: dict[str, float]) -> dict[str, float]:
        if self.mode == "stage_profile" and stage_band in self.profiles:
            return dict(self.profiles[stage_band])
        return dict(default)


class ScoringCalibration(Strict):
    """An explicit overall-score calibration; evidence and certification retain their baseline."""

    multiplier: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    certification_basis: Literal["baseline"] = "baseline"


class Corroboration(Strict):
    """How many separate passages must carry a rung before the ladder credits it.

    One sentence can match a lexicon by accident; the same accident in a second passage is far less
    likely. A rung that is absent from ``min_passages`` needs one passage, as before.
    """

    min_passages: dict[str, int] = Field(default_factory=dict)

    def required(self, rung: str) -> int:
        return max(1, int(self.min_passages.get(rung, 1)))


class Scoring(Strict):
    level_min: int
    level_max: int
    criterion_ratio: str
    pillar_aggregation: Literal["equal_mean", "materiality_weighted"]
    pillar_weight_profiles: PillarWeightProfiles = PillarWeightProfiles()
    calibration: ScoringCalibration = Field(default_factory=ScoringCalibration)
    corroboration: Corroboration = Field(default_factory=Corroboration)
    score_scale: float
    score_cap: float
    low_confidence_cap: LowConfidenceCap
    excluded_coverage_states: list[str]
    missing_level: int
    effectiveness_min_rung: str


class CorroborationBonus(Strict):
    two_sources: float
    three_or_more: float
    scaled_by_materiality: bool


class Clamp(Strict):
    min: float
    max: float


class PartialCeiling(Strict):
    value: float
    content_status: str


class ContradictionPenalty(Strict):
    per_admissible_contradicting_link: float
    max: float
    content_status: str


class OmissionPenalty(Strict):
    per_omitted_span: float
    max: float
    content_status: str


class SecondOpinion(Strict):
    disagreement_levels_for_penalty: int
    penalty: float
    disagreement_levels_for_review: int
    content_status: str


class ConfidenceComponents(Strict):
    """The published decomposition of evidence confidence (decision D13). Weights sum to 1."""

    source: str = ""
    source_credibility: float = 0.40
    evidence_type: float = 0.30
    cross_source_validation: float = 0.20
    recency: float = 0.10
    cross_source_full_at: int = 3
    evidence_type_credit: dict[str, float] = {}
    content_status: str = "draft"

    @property
    def weights(self) -> dict[str, float]:
        return {
            "source_credibility": self.source_credibility,
            "evidence_type": self.evidence_type,
            "cross_source_validation": self.cross_source_validation,
            "recency": self.recency,
        }


class Confidence(Strict):
    model: Literal["components", "legacy_contribution"] = "legacy_contribution"
    components: ConfidenceComponents = ConfidenceComponents()
    base_contribution: float
    corroboration_bonus: CorroborationBonus
    execution_bonus_from: str
    execution_bonus_mode: Literal["max_over_links", "per_link_mean"]
    clamp: Clamp
    partial_ceiling: PartialCeiling
    contradiction_penalty: ContradictionPenalty
    omission_penalty: OmissionPenalty
    second_opinion: SecondOpinion


class StageSizeRow(Strict):
    stage_band: str
    size_band: str
    threshold: float


class StageSizeTable(Strict):
    content_status: str
    rows: list[StageSizeRow]


class Certification(Strict):
    threshold_mode: Literal["universal", "stage_size"]
    threshold: float
    min_confidence: float
    require_evidence_in_every_pillar: bool = False
    validity_months: int
    stage_size_table: StageSizeTable

    def threshold_for(self, stage_band: str, size_band: str) -> float:
        if self.threshold_mode == "universal":
            return self.threshold
        for row in self.stage_size_table.rows:
            if row.stage_band == stage_band and row.size_band == size_band:
                return row.threshold
        raise ValueError(f"no certification threshold configured for {stage_band}/{size_band}")


class Outcome(Strict):
    access_limited_unavailable_share: float
    insufficient_min_observed_criteria: int
    governance_baseline_min_admissible_links: int
    content_status: str
    # 6.0.0: when the assessment is access limited or rests on too few criteria, publish no overall
    # score. One assessable criterion out of twenty does not describe an organization.
    withhold_score_without_coverage: bool = False


class DecayCurve(Strict):
    half_life_months: float
    floor: float
    legacy_source: list[str] = []


class SimpleCurve(Strict):
    half_life_months: float
    floor: float


class FreshnessLabel(Strict):
    min: float
    label: str


class Freshness(Strict):
    default_window_months: int
    undated_age_months: float
    certificate_full_weight_until_expiry: bool
    decay_curves: dict[str, DecayCurve]
    contradicting_press_curve: SimpleCurve
    labels: list[FreshnessLabel]


class Band(Strict):
    low: float
    high: float


class ReviewTriggers(Strict):
    borderline_confidence_band: Band
    contradictory_coverage: bool
    unverified_incidents: bool
    certification_request: bool
    no_finding_with_admissible_support: bool
    unexercised_capability: bool = True
    incident_response: bool = True
    self_reported_monitoring: bool = True
    content_status: str


class TermList(Strict):
    terms: list[str]


class AiContextLexicon(Strict):
    """AI terminology, and the rung from which evidence must be about the organization's AI practice.

    ``terms`` is any mention of AI; it scopes adverse events. ``practice_terms`` are phrases that show
    a passage is about AI being governed, built or used ("responsible AI", "AI systems", "model
    cards"), as opposed to a passing mention such as a director's degree or a product name.
    ``required_from_rung`` names the lowest maturity rung that needs a practice term in the quote, its
    section heading or the document title. General corporate governance then earns credit below that
    rung only. ``None`` keeps the earlier behaviour: any AI term, Safety pillar only.
    """

    terms: list[str] = Field(default_factory=list)
    practice_terms: list[str] = Field(default_factory=list)
    required_from_rung: str | None = None


class EvidenceQuality(Strict):
    """What a quoted passage must look like before it earns a control or execution rung.

    Keyword evidence is only as good as its guards. Every default leaves a guard off, so a manifest
    that omits this block behaves as before.

    * ``min_words_for_control`` and ``min_prose_share`` keep tables of contents, name lists and table
      rows out: a control is described in a sentence.
    * ``caution_terms`` mark risk-factor language, which describes what could go wrong and is neither
      a commitment nor a control.
    * ``hint_in_quote_from_rung`` requires the criterion's own vocabulary in the quoted text, not only
      in the heading above it.
    * ``control_max_gap_chars`` requires the accountable owner and the procedure to stand together.
    * ``execution_max_gap_chars`` requires the date and the result to stand together, and
      ``execution_voice_terms`` requires the organization's own voice; ``reported_speech_terms``
      mark a quotation of someone else.
    """

    min_words_for_control: int = 6
    min_prose_share: float = 0.0
    caution_terms: list[str] = Field(default_factory=list)
    hint_in_quote_from_rung: str | None = None
    control_max_gap_chars: int | None = None
    execution_max_gap_chars: int | None = None
    execution_voice_terms: list[str] = Field(default_factory=list)
    reported_speech_terms: list[str] = Field(default_factory=list)


class ControlLexicon(Strict):
    owner_terms: list[str]
    threshold_terms: list[str]
    procedure_terms: list[str] = Field(default_factory=list)


class ExecutionDates(Strict):
    """A record that something was done: a result beside a date, or beside a quantity.

    ``quantity_terms`` (6.0.0) lets "14 model reviews were completed" count as a record even when
    the sentence carries no date. Empty keeps the earlier dated-only behaviour.
    """

    terms: list[str]
    result_terms: list[str]
    quantity_terms: list[str] = Field(default_factory=list)


class ExecutionCategory(Strict):
    weight: float
    patterns: list[str]


class ExecutionLevels(Strict):
    verified_if: str
    partial_if: str
    asserted_if: str


class ExecutionLexicon(Strict):
    categories: dict[str, ExecutionCategory]
    levels: ExecutionLevels


class NegativeRule(Strict):
    code: str
    publisher_types: list[str]
    terms: list[str]
    severity: str
    initial_status: str
    affected_pillars: list[str]
    description: str


class NegativeDefault(Strict):
    severity_by_tier: dict[str, str]
    initial_status: str
    affected_pillars: list[str]
    description: str


class NegativeSignals(Strict):
    rules: list[NegativeRule]
    default: NegativeDefault
    wording_rules: list[str]
    hypothetical_terms: list[str] = Field(default_factory=list)


class Irrelevance(Strict):
    require_hint_match: bool


class Lexicons(Strict):
    commitment: TermList
    control: ControlLexicon
    execution_dates: ExecutionDates
    independent_verification: TermList
    execution: ExecutionLexicon
    negative_signals: NegativeSignals
    injection: TermList
    irrelevance: Irrelevance
    focus_areas: dict[str, TermList] = {}
    ai_context: AiContextLexicon = Field(default_factory=AiContextLexicon)
    evidence_quality: EvidenceQuality = Field(default_factory=EvidenceQuality)


class EvidenceStrengthLabel(Strict):
    min_share: float
    label: str


class ReportConfig(Strict):
    """Report-only settings: labels for evidence strength and how pillar status is derived."""

    evidence_strength_labels: list[EvidenceStrengthLabel] = []
    maturity_status_from: Literal["rung_reached_by_half"] = "rung_reached_by_half"
    content_status: str = "draft"

    def strength_label(self, share: float) -> str:
        for row in sorted(self.evidence_strength_labels, key=lambda r: -r.min_share):
            if share >= row.min_share:
                return row.label
        return "None"


class Methodology(Strict):
    version: str
    status: str
    effective_from: date | None
    approved_by: str | None
    change_record_uri: str | None
    product: Product
    scoring: Scoring
    confidence: Confidence
    certification: Certification
    outcome: Outcome
    freshness: Freshness
    review_triggers: ReviewTriggers
    lexicons: Lexicons
    report: ReportConfig = ReportConfig()


class MethodologyFile(Strict):
    methodology: Methodology


class PillarDef(Strict):
    code: str
    name: str
    legacy_id: str
    display_order: int
    weight: float
    description: str


class PillarsFile(Strict):
    pillars: list[PillarDef]


class LevelDef(Strict):
    level: int
    required_maturity_rung: str
    descriptor: str


class ApplicabilityDef(Strict):
    condition: str
    effect: str


class IndicatorDef(Strict):
    code: str
    kind: str
    label: str | None


class CriterionDef(Strict):
    code: str
    pillar: str
    name: str
    legacy_id: str
    content_status: str
    definition: str
    materiality: str
    materiality_weight: float
    weight: float
    freshness_window_months: int
    target_types: list[str]
    applicability: list[ApplicabilityDef]
    levels: list[LevelDef]
    retrieval_hints: list[str]
    indicators: list[IndicatorDef]
    focus_areas: list[str] = []

    def level_for_rung(self, rung_rank: int, rung_ranks: dict[str, int]) -> int:
        """Highest level whose required rung rank is at or below ``rung_rank``."""
        best = min(lv.level for lv in self.levels)
        for lv in sorted(self.levels, key=lambda x: x.level):
            if rung_ranks[lv.required_maturity_rung] <= rung_rank:
                best = lv.level
        return best


class CriterionFile(Strict):
    criterion: CriterionDef


class RuleDef(Strict):
    code: str
    kind: str
    scope: str
    run_order: int
    expression_ref: str
    description: str
    parameters: dict[str, Any] = {}


class Ruleset(Strict):
    version: str
    rules: list[RuleDef]


class RulesFile(Strict):
    ruleset: Ruleset


class DecisionDef(Strict):
    id: str
    title: str
    needed_by: str
    status: str
    recommendation: str
    current: str
    configured_in: str


class DecisionsFile(Strict):
    decisions: list[DecisionDef]


class ExampleRecord(Strict):
    entity: str
    description: str
    record: dict[str, Any]
    expect_error: str | None = None
    path: str = ""


# --------------------------------------------------------------------------- manifest


class Manifest(BaseModel):
    """The fully loaded manifest. ``hash`` is the SHA-256 over the canonical content."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    ontology: OntologyFile
    vocabularies: dict[str, VocabularyDef]
    methodology: Methodology
    pillars: list[PillarDef]
    criteria: list[CriterionDef]
    ruleset: Ruleset
    decisions: list[DecisionDef]
    examples_valid: list[ExampleRecord] = []
    examples_invalid: list[ExampleRecord] = []
    hash: str = ""
    source_dir: Path | None = None

    # -- lookups ---------------------------------------------------------------
    @property
    def ontology_version(self) -> str:
        return self.ontology.ontology.version

    @property
    def methodology_version(self) -> str:
        return self.methodology.version

    @property
    def schema_name(self) -> str:
        return self.ontology.ontology.schema_name

    @property
    def entities(self) -> list[EntityDef]:
        return self.ontology.entities

    @property
    def entity_names(self) -> list[str]:
        return [e.name for e in self.ontology.entities]

    def entity(self, name: str) -> EntityDef:
        for e in self.ontology.entities:
            if e.name == name:
                return e
        raise KeyError(name)

    def entity_by_table(self, table: str) -> EntityDef:
        for e in self.ontology.entities:
            if e.table == table:
                return e
        raise KeyError(table)

    def vocabulary(self, code: str) -> VocabularyDef:
        return self.vocabularies[code]

    def criterion(self, code: str) -> CriterionDef:
        for c in self.criteria:
            if c.code == code:
                return c
        raise KeyError(code)

    def pillar(self, code: str) -> PillarDef:
        for p in self.pillars:
            if p.code == code:
                return p
        raise KeyError(code)

    def criteria_for_pillar(self, pillar_code: str) -> list[CriterionDef]:
        return [c for c in self.criteria if c.pillar == pillar_code]

    def rule(self, code: str) -> RuleDef:
        for r in self.ruleset.rules:
            if r.code == code:
                return r
        raise KeyError(code)

    def rung_ranks(self) -> dict[str, int]:
        voc = self.vocabulary("maturity_rung")
        return {v.code: int(v.rank or 0) for v in voc.values}

    def fks_for(self, entity: str) -> list[FKDef]:
        out: list[FKDef] = []
        for rel in self.ontology.relations:
            out.extend(fk for fk in rel.fks if fk.entity == entity)
        return out

    def tables_in_dependency_order(self) -> list[EntityDef]:
        """Entities ordered so that every FK target comes first (self references ignored)."""
        remaining = {e.name: e for e in self.ontology.entities}
        deps: dict[str, set[str]] = {name: {fk.to for fk in self.fks_for(name) if fk.to != name} for name in remaining}
        ordered: list[EntityDef] = []
        while remaining:
            ready = sorted(n for n, d in deps.items() if n in remaining and not (d & set(remaining)))
            if not ready:
                raise ValueError(f"circular foreign keys among {sorted(remaining)}")
            for n in ready:
                ordered.append(remaining.pop(n))
        return ordered

    def legacy_criterion_aliases(self) -> dict[str, str]:
        return {c.legacy_id: c.code for c in self.criteria}

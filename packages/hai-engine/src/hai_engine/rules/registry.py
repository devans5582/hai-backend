"""Rule registry.

Rules are pure functions registered under a code with ``@criterion_rule`` or
``@assessment_rule``. The ruleset in ``rules.yaml`` names each implementation by
``module:function``; :func:`resolve` refuses to start when a reference does not
point at a function registered under the same code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hai_ontology.meta import Manifest, RuleDef

if TYPE_CHECKING:
    from hai_engine.rules.context import AssessmentContext, AssessmentState, CriterionContext, CriterionState

CriterionRuleFn = Callable[["CriterionContext", "CriterionState", dict[str, Any]], str]
AssessmentRuleFn = Callable[["AssessmentContext", "AssessmentState", dict[str, Any]], str]


class RuleRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Registered:
    code: str
    scope: str
    fn: Callable[..., str]

    @property
    def expression_ref(self) -> str:
        return f"{self.fn.__module__}:{self.fn.__name__}"


_REGISTRY: dict[str, Registered] = {}


def criterion_rule(code: str) -> Callable[[CriterionRuleFn], CriterionRuleFn]:
    def deco(fn: CriterionRuleFn) -> CriterionRuleFn:
        _register(code, "criterion", fn)
        return fn

    return deco


def assessment_rule(code: str) -> Callable[[AssessmentRuleFn], AssessmentRuleFn]:
    def deco(fn: AssessmentRuleFn) -> AssessmentRuleFn:
        _register(code, "assessment", fn)
        return fn

    return deco


def _register(code: str, scope: str, fn: Callable[..., str]) -> None:
    existing = _REGISTRY.get(code)
    if existing is not None and existing.fn is not fn:
        raise RuleRegistryError(f"rule {code} is already registered by {existing.expression_ref}")
    _REGISTRY[code] = Registered(code, scope, fn)
    setattr(fn, "__rule_code__", code)  # noqa: B010 - marker attribute for introspection


def registered() -> dict[str, Registered]:
    return dict(_REGISTRY)


def implementations() -> dict[str, str]:
    """Rule code to ``module:function``; what the ontology validator consumes."""
    return {code: r.expression_ref for code, r in sorted(_REGISTRY.items())}


@dataclass(frozen=True)
class ResolvedRule:
    rule: RuleDef
    fn: Callable[..., str]


def resolve(manifest: Manifest) -> tuple[list[ResolvedRule], list[ResolvedRule]]:
    """Resolve the ruleset to (criterion rules, assessment rules) in run order, or refuse."""
    problems: list[str] = []
    criterion: list[ResolvedRule] = []
    assessment: list[ResolvedRule] = []
    for rule in manifest.ruleset.rules:
        reg = _REGISTRY.get(rule.code)
        if reg is None:
            problems.append(f"{rule.code}: no implementation registered")
            continue
        if reg.expression_ref != rule.expression_ref:
            problems.append(f"{rule.code}: ruleset names {rule.expression_ref} but {reg.expression_ref} is registered")
            continue
        if reg.scope != rule.scope:
            problems.append(f"{rule.code}: registered as a {reg.scope} rule but the ruleset says {rule.scope}")
            continue
        target = criterion if rule.scope == "criterion" else assessment
        target.append(ResolvedRule(rule, reg.fn))
    if problems:
        raise RuleRegistryError("ruleset does not resolve: " + "; ".join(problems))
    criterion.sort(key=lambda r: r.rule.run_order)
    assessment.sort(key=lambda r: r.rule.run_order)
    return criterion, assessment

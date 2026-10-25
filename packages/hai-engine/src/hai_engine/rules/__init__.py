"""Rules are data in rules.yaml; implementations live here and are registered by code.

``RULE_IMPLEMENTATIONS`` is what ``hai-ontology validate --implementations
hai_engine.rules`` reads.
"""

from hai_engine.rules import builtin as _builtin  # noqa: F401 - importing registers the rules
from hai_engine.rules.engine import EngineResult, RuleEngine
from hai_engine.rules.registry import RuleRegistryError, assessment_rule, criterion_rule, implementations, resolve

RULE_IMPLEMENTATIONS = implementations()

__all__ = [
    "RULE_IMPLEMENTATIONS",
    "EngineResult",
    "RuleEngine",
    "RuleRegistryError",
    "assessment_rule",
    "criterion_rule",
    "implementations",
    "resolve",
]

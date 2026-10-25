"""Freshness: decay, staleness and certificate validity, computed against a fixed ``as_of``.

Pure functions. The rules engine passes the snapshot's ``frozen_at`` so replay
is deterministic; nothing here reads the clock.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from hai_ontology.meta import Methodology

DAYS_PER_MONTH = 30.44


def _to_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def months_between(earlier: date | datetime, later: date | datetime) -> float:
    return (_to_date(later) - _to_date(earlier)).days / DAYS_PER_MONTH


def decay(half_life_months: float, floor: float, age_months: float) -> float:
    """Exponential decay with a floor: ``max(floor, exp(-ln2 / half_life * age))``."""
    if age_months <= 0:
        return 1.0
    value = math.exp(-math.log(2) / half_life_months * age_months)
    return max(floor, round(value, 3))


def decay_multiplier(
    methodology: Methodology,
    publisher_type: str,
    published_at: date | datetime | None,
    as_of: date | datetime,
    *,
    contradicting_press: bool = False,
    certificate_valid_until: date | datetime | None = None,
) -> float:
    """The freshness multiplier for one piece of evidence.

    * An active certificate (valid_until in the future) has full weight; after
      expiry it decays from the expiry date (Phase 6 FIX-10).
    * Undated evidence is decayed with the methodology's assumed age, never
      treated as current and never called stale.
    """
    fr = methodology.freshness
    if contradicting_press and publisher_type == "press":
        half_life, floor = fr.contradicting_press_curve.half_life_months, fr.contradicting_press_curve.floor
    else:
        curve = fr.decay_curves.get(publisher_type) or fr.decay_curves["default"]
        half_life, floor = curve.half_life_months, curve.floor
    if certificate_valid_until is not None and fr.certificate_full_weight_until_expiry:
        if _to_date(certificate_valid_until) >= _to_date(as_of):
            return 1.0
        return decay(half_life, floor, months_between(certificate_valid_until, as_of))
    if published_at is None:
        return decay(half_life, floor, fr.undated_age_months)
    return decay(half_life, floor, months_between(published_at, as_of))


def is_stale(published_at: date | datetime | None, as_of: date | datetime, window_months: int) -> bool:
    """Dated evidence older than the window is stale. Undated evidence is never stale."""
    if published_at is None:
        return False
    return months_between(published_at, as_of) > window_months


def certificate_active(valid_until: date | datetime | None, as_of: date | datetime) -> bool:
    return valid_until is not None and _to_date(valid_until) >= _to_date(as_of)


def freshness_label(methodology: Methodology, percent: float | None) -> str:
    if percent is None:
        return "Not assessed"
    for row in sorted(methodology.freshness.labels, key=lambda r: -r.min):
        if percent >= row.min:
            return row.label
    return methodology.freshness.labels[-1].label

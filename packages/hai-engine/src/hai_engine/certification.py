"""Certification: only a named reviewer signs; HMAC signature; public verification; expiry; revocation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from hai_core.auth import Principal
from hai_core.db.store import Store
from hai_core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from hai_core.generated.enums import CertificationOutcome
from hai_core.generated.models import Assessment, AssessmentResult, CertificationDecision
from hai_ontology.meta import Methodology


def signature_payload(
    assessment_id: UUID,
    result_id: UUID,
    result_sha256: str,
    reviewer_id: str,
    decision: str,
    signed_at: datetime,
    expires_at: datetime | None,
) -> str:
    return "|".join(
        [
            str(assessment_id),
            str(result_id),
            result_sha256,
            reviewer_id,
            decision,
            signed_at.isoformat(),
            expires_at.isoformat() if expires_at else "",
        ]
    )


def sign_payload(key: str, payload: str) -> str:
    return hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def certificate_number(assessment_id: UUID, signed_at: datetime) -> str:
    return f"HAI-{signed_at.year}-{hashlib.sha256(str(assessment_id).encode()).hexdigest()[:6].upper()}-{secrets.token_hex(2).upper()}"  # noqa: E501


@dataclass(frozen=True)
class Verification:
    valid: bool
    status: str  # valid | expired | revoked | not_found | tampered
    certificate_number: str
    organization: str | None = None
    hai_score: float | None = None
    signed_at: str | None = None
    expires_at: str | None = None
    reviewer: str | None = None
    methodology_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CertificationService:
    def __init__(self, methodology: Methodology, signing_key: str) -> None:
        self.methodology = methodology
        self.key = signing_key

    def sign(
        self,
        store: Store,
        *,
        assessment: Assessment,
        result: AssessmentResult,
        principal: Principal,
        decision: str,
        reason: str,
        now: datetime | None = None,
    ) -> CertificationDecision:
        if not principal.is_reviewer:
            raise ForbiddenError("only a named reviewer can sign a certification decision (IC-13)")
        if decision not in (CertificationOutcome.CERTIFIED.value, CertificationOutcome.NOT_CERTIFIED.value):
            raise ValidationFailedError("decision must be certified or not_certified")
        if decision == CertificationOutcome.CERTIFIED.value and result.gate_reasons:
            raise ValidationFailedError(
                "gates failed: " + "; ".join(result.gate_reasons), details={"gate_reasons": list(result.gate_reasons)}
            )
        when = now or datetime.now(UTC)
        expires = (
            when + timedelta(days=30 * self.methodology.certification.validity_months)
            if decision == CertificationOutcome.CERTIFIED.value
            else None
        )
        payload = signature_payload(
            assessment.id, result.id, result.result_sha256, principal.id, decision, when, expires
        )
        row = CertificationDecision(
            assessment_id=assessment.id,
            result_id=result.id,
            threshold_applied=self.methodology.certification.threshold,
            decision=CertificationOutcome(decision),
            gate_reasons=list(result.gate_reasons),
            reviewer_id=principal.id,
            signed_at=when,
            expires_at=expires,
            certificate_number=certificate_number(assessment.id, when)
            if decision == CertificationOutcome.CERTIFIED.value
            else None,
            signature=sign_payload(self.key, payload),
        )
        return store.insert(row, reason=reason)

    def revoke(
        self,
        store: Store,
        *,
        current: CertificationDecision,
        principal: Principal,
        reason: str,
        now: datetime | None = None,
    ) -> CertificationDecision:
        if not principal.is_reviewer:
            raise ForbiddenError("only a named reviewer can revoke a certification")
        if current.decision is not CertificationOutcome.CERTIFIED:
            raise ConflictError("only a certified decision can be revoked")
        when = now or datetime.now(UTC)
        payload = signature_payload(
            current.assessment_id,
            current.result_id,
            "revoked",
            principal.id,
            CertificationOutcome.REVOKED.value,
            when,
            None,
        )
        row = CertificationDecision(
            assessment_id=current.assessment_id,
            result_id=current.result_id,
            threshold_applied=current.threshold_applied,
            decision=CertificationOutcome.REVOKED,
            gate_reasons=[reason],
            reviewer_id=principal.id,
            signed_at=when,
            expires_at=None,
            certificate_number=None,
            signature=sign_payload(self.key, payload),
        )
        return store.supersede(current, row, reason=reason)

    def verify(self, store: Store, number: str, *, now: datetime | None = None) -> Verification:
        rows = store.find(CertificationDecision, where={"certificate_number": number})
        if not rows:
            return Verification(False, "not_found", number)
        cert = rows[-1]
        if store.find(CertificationDecision, where={"supersedes_id": cert.id}):
            return Verification(
                False, "revoked", number, signed_at=cert.signed_at.isoformat(), reviewer=cert.reviewer_id
            )
        result = store.get(AssessmentResult, cert.result_id)
        assessment = store.get(Assessment, cert.assessment_id)
        if result is None or assessment is None:
            return Verification(False, "not_found", number)
        payload = signature_payload(
            cert.assessment_id,
            cert.result_id,
            result.result_sha256,
            cert.reviewer_id,
            cert.decision.value,
            cert.signed_at,
            cert.expires_at,
        )
        if not hmac.compare_digest(sign_payload(self.key, payload), cert.signature):
            return Verification(False, "tampered", number)
        when = now or datetime.now(UTC)
        from hai_core.generated.models import Organization

        org = store.get(Organization, assessment.org_id)
        status = "expired" if cert.expires_at and cert.expires_at < when else "valid"
        return Verification(
            status == "valid",
            status,
            number,
            organization=org.display_name if org else None,
            hai_score=float(result.hai_score) if result.hai_score is not None else None,
            signed_at=cert.signed_at.isoformat(),
            expires_at=cert.expires_at.isoformat() if cert.expires_at else None,
            reviewer=cert.reviewer_id,
            methodology_version=assessment.methodology_version,
        )

    def current_for(self, store: Store, assessment_id: UUID) -> CertificationDecision | None:
        rows = store.find(CertificationDecision, where={"assessment_id": assessment_id}, order_by="created_at")
        superseded = {r.supersedes_id for r in rows if r.supersedes_id}
        live = [r for r in rows if r.id not in superseded]
        return live[-1] if live else None

    def require_current(self, store: Store, assessment_id: UUID) -> CertificationDecision:
        current = self.current_for(store, assessment_id)
        if current is None:
            raise NotFoundError("no certification decision for this assessment")
        return current

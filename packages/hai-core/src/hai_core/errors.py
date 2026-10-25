"""Typed errors shared by every service. The API maps them to the error envelope."""

from __future__ import annotations

from typing import Any


class HaiError(Exception):
    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def envelope(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(HaiError):
    code = "not_found"
    http_status = 404


class ConflictError(HaiError):
    code = "conflict"
    http_status = 409


class ValidationFailedError(HaiError):
    code = "validation_failed"
    http_status = 422


class UnauthorizedError(HaiError):
    code = "unauthorized"
    http_status = 401


class ForbiddenError(HaiError):
    code = "forbidden"
    http_status = 403


class IntegrityViolationError(HaiError):
    code = "integrity_violation"
    http_status = 409


class AppendOnlyError(IntegrityViolationError):
    code = "append_only"


class ImmutableFieldError(IntegrityViolationError):
    code = "immutable_field"


class InvalidTransitionError(IntegrityViolationError):
    code = "invalid_transition"


class CertificationRequiredError(IntegrityViolationError):
    code = "certification_required"


class ConfigurationError(HaiError):
    code = "configuration_error"
    http_status = 500


class UnavailableError(HaiError):
    code = "unavailable"
    http_status = 503

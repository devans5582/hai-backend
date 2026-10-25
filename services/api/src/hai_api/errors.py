"""Error handling: every error is ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from hai_core.errors import HaiError

log = logging.getLogger(__name__)


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HaiError)
    async def _hai(request: Request, exc: HaiError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.envelope(), headers=_request_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path", "header")]
            fields[".".join(loc) or "body"] = str(err.get("msg", "invalid"))
        return JSONResponse(
            status_code=422,
            content=envelope("validation_failed", "request validation failed", {"fields": fields}),
            headers=_request_id(request),
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            422: "validation_failed",
        }.get(exc.status_code, "http_error")
        detail = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(code, detail),
            headers={**_request_id(request), **(exc.headers or {})},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled error", extra={"request_id": getattr(request.state, "request_id", None), "error": str(exc)}
        )
        return JSONResponse(
            status_code=500,
            content=envelope("internal_error", "an unexpected error occurred"),
            headers=_request_id(request),
        )


def _request_id(request: Request) -> dict[str, str]:
    rid = getattr(request.state, "request_id", None)
    return {"X-Request-Id": str(rid)} if rid else {}

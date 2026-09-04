"""Request tracing, safe HTTP headers, and JSON production logs."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_PATHS = ("/api/v1/analysis", "/api/v1/methods/fuzdrop/import")
request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def current_request_id() -> str:
    return request_id_context.get()


class JsonLogFormatter(logging.Formatter):
    """Serialize standard and allow-listed operational fields without request bodies."""

    _optional_fields = (
        "request_id",
        "job_id",
        "method",
        "status",
        "runtime_ms",
        "sequence_length",
        "sequence_sha256",
    )

    def __init__(self, *, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": self.service,
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", current_request_id()),
        }
        for field in self._optional_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            # Keep the traceback in server logs. It is never returned in an HTTP response.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(*, service: str, level: str, structured: bool) -> None:
    """Configure process logging once at startup from explicit deployment settings."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    if not structured:
        return
    formatter = JsonLogFormatter(service=service)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    handlers = list(root.handlers)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        handlers.extend(logging.getLogger(name).handlers)
    for handler in dict.fromkeys(handlers):
        handler.setFormatter(formatter)


def _origin(value: str) -> str:
    return value.rstrip("/").lower()


def _configured_origins(value: object) -> set[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = [str(item) for item in value]
    else:
        items = []
    return {_origin(item.strip()) for item in items if item.strip()}


class ProductionHTTPMiddleware(BaseHTTPMiddleware):
    """Add request IDs, origin checks, no-store policy, and safe response headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if _REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        token = request_id_context.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        response: Response
        try:
            rejection = self._csrf_rejection(request, request_id)
            response = rejection if rejection is not None else await call_next(request)
        finally:
            request_id_context.reset(token)
        runtime_ms = round((time.perf_counter() - started) * 1000, 3)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), geolocation=(), microphone=()"
        )
        if request.url.path.startswith(
            ("/api/v1/analysis", "/api/v1/methods/fuzdrop/import")
        ):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
        logging.getLogger("llps.http").info(
            "HTTP request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "status": response.status_code,
                "runtime_ms": runtime_ms,
            },
        )
        return response

    @staticmethod
    def _csrf_rejection(request: Request, request_id: str) -> Response | None:
        if request.method not in _UNSAFE_METHODS or not request.url.path.startswith(_CSRF_PATHS):
            return None
        origin = request.headers.get("origin")
        if not origin:
            # Non-browser API clients may omit Origin. Browser cookie requests supply it.
            return None
        settings = request.app.state.settings
        allowed = _configured_origins(getattr(settings, "cors_allowed_origins", ()))
        public_base_url = getattr(settings, "public_base_url", None)
        if public_base_url:
            allowed.add(_origin(str(public_base_url)))
        if _origin(origin) in allowed:
            return None
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "CSRF_ORIGIN_REJECTED",
                    "message": "The request origin is not allowed.",
                    "request_id": request_id,
                }
            },
        )

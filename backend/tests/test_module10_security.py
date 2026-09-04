from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.health import ops_router
from app.api.session import analysis_owner
from app.api.system import router as system_router
from app.api.system import version_router
from app.core.config import Settings
from app.core.observability import ProductionHTTPMiddleware
from app.main import create_app
from app.schemas.lreca import LRECAHealth
from app.schemas.seg import SEGHealth
from app.services.method_registry import MethodRegistry
from app.services.rate_limits import RatePolicy, RedisRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []

    def eval(self, _script: str, _number_of_keys: int, key: str, _ttl: int) -> int:
        self.keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def test_rate_limit_combines_session_and_address_without_plain_identifiers(monkeypatch) -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(
        redis,
        secret="module10-test-secret-that-is-long-enough",
        policies={"analysis_submit": RatePolicy(limit=2, window_seconds=60)},
        ip_multiplier=4,
    )
    monkeypatch.setattr("app.services.rate_limits.time.time", lambda: 120.0)

    async def run() -> list[int | None]:
        return [
            await limiter.check(
                action="analysis_submit",
                owner_id="private-owner-id",
                client_address="192.0.2.10",
            )
            for _ in range(3)
        ]

    assert asyncio.run(run()) == [None, None, 60]
    assert len(redis.keys) == 6
    assert all("private-owner-id" not in key and "192.0.2.10" not in key for key in redis.keys)


def _middleware_app() -> FastAPI:
    application = FastAPI()
    application.state.settings = SimpleNamespace(
        cors_allowed_origins="http://localhost,http://127.0.0.1:3000",
        public_base_url="http://localhost",
    )
    application.add_middleware(ProductionHTTPMiddleware)

    @application.post("/api/v1/analysis")
    async def submit() -> dict[str, bool]:
        return {"accepted": True}

    return application


def test_request_id_security_headers_and_private_no_store() -> None:
    with TestClient(_middleware_app()) as client:
        response = client.post(
            "/api/v1/analysis",
            headers={"Origin": "http://localhost", "X-Request-ID": "trace_123"},
        )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace_123"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_csrf_origin_rejection_is_structured_and_traceable() -> None:
    with TestClient(_middleware_app()) as client:
        response = client.post(
            "/api/v1/analysis",
            headers={"Origin": "https://attacker.invalid", "X-Request-ID": "csrf-test"},
        )
    assert response.status_code == 403
    assert response.headers["x-request-id"] == "csrf-test"
    assert response.json() == {
        "detail": {
            "code": "CSRF_ORIGIN_REJECTED",
            "message": "The request origin is not allowed.",
            "request_id": "csrf-test",
        }
    }


class UnavailableLRECA:
    async def load(self) -> None:
        return None

    async def healthcheck(self) -> LRECAHealth:
        return LRECAHealth()

    async def close(self) -> None:
        return None


class UnavailableSEG:
    async def load(self) -> None:
        return None

    async def healthcheck(self) -> SEGHealth:
        return SEGHealth()

    async def close(self) -> None:
        return None


def test_operational_health_and_version_are_safe_and_liveness_is_independent() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    application = FastAPI()
    application.state.settings = settings
    application.state.database_engine = create_engine("sqlite://")
    application.state.rate_limiter = None
    application.state.analysis_service = SimpleNamespace(
        healthcheck=lambda: asyncio.sleep(
            0, result={"ready": True, "queue": True, "worker": None, "depth": 0}
        )
    )
    application.state.method_registry = MethodRegistry(
        {"lreca": UnavailableLRECA(), "seg": UnavailableSEG()}
    )
    application.include_router(ops_router)
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(version_router, prefix="/api/v1")
    try:
        with TestClient(application) as client:
            live = client.get("/health/live")
            ready = client.get("/health/ready")
            version = client.get("/api/v1/version")
        assert live.status_code == 200 and live.json()["live"] is True
        assert ready.status_code == 200 and ready.json()["ready"] is True
        assert version.status_code == 200
        assert version.json()["application_version"] == "0.10.0"
        assert version.json()["result_schema_version"] == "1.0"
        serialized = version.text
        assert "human_1_RCNN_ECA_parallel_089-0.9802.pt" in serialized
        assert "C:\\\\" not in serialized and "/opt/" not in serialized
    finally:
        application.state.database_engine.dispose()


class AlwaysLimit:
    async def check(self, **_kwargs) -> int:
        return 7


def test_analysis_rate_limit_remains_a_structured_429() -> None:
    application = create_app(
        Settings(_env_file=None, database_url="sqlite://"),
        lreca_adapter=UnavailableLRECA(),
        seg_adapter=UnavailableSEG(),
    )
    with TestClient(application) as client:
        application.state.rate_limiter = AlwaysLimit()
        response = client.post(
            "/api/v1/analysis",
            json={"sequence": "AAAA", "selected_methods": ["dismeta"]},
            headers={"X-Request-ID": "limited-request"},
        )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"
    assert response.json()["detail"] == {
        "code": "RATE_LIMITED",
        "message": "Too many requests. Retry after the indicated interval.",
        "retry_after_seconds": 7,
        "request_id": "limited-request",
    }


def test_cookie_secure_flag_tracks_public_https_without_breaking_local_http() -> None:
    def cookie_app(public_https: bool) -> FastAPI:
        application = FastAPI()
        application.state.settings = Settings(_env_file=None, public_https=public_https)

        @application.get("/")
        async def issue(
            request: Request,
            response: Response,
            _owner: str = Depends(analysis_owner),
        ) -> dict[str, bool]:
            return {"ok": True}

        return application

    with TestClient(cookie_app(False)) as client:
        local_cookie = client.get("/").headers["set-cookie"]
    with TestClient(cookie_app(True), base_url="https://example.test") as client:
        secure_cookie = client.get("/").headers["set-cookie"]
    assert "HttpOnly" in local_cookie and "SameSite=lax" in local_cookie
    assert "Secure" not in local_cookie
    assert "Secure" in secure_cookie

"""Public deployment status and immutable scientific-version metadata."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from lreca_runtime.metadata import CHECKPOINT_NAME, CHECKPOINT_SHA256

router = APIRouter(prefix="/system", tags=["system"])
version_router = APIRouter(tags=["system"])
LRECA_REPOSITORY_COMMIT = "0b4b48ab7870529a34028c6e30dfba42eddbf215"


class ComponentStatus(BaseModel):
    status: Literal["ready", "degraded", "unavailable", "blocked", "not_applicable"]
    mode: str | None = None


class SystemStatusResponse(BaseModel):
    service: str = "llps-backend"
    version: str = __version__
    module: Literal[10] = 10
    ready: bool
    components: dict[str, ComponentStatus]


class VersionResponse(BaseModel):
    application_version: str = __version__
    result_schema_version: Literal["1.0"] = "1.0"
    module: Literal[10] = 10
    lreca: dict[str, str]
    seg: dict[str, str | int | float]
    fuzdrop: dict[str, str]
    dismeta: dict[str, str]
    ensemble: dict[str, str | float]


def _database_ping(engine: Any) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def deployment_status(request: Request) -> SystemStatusResponse:
    settings = request.app.state.settings
    engine = getattr(request.app.state, "database_engine", None)
    database_ok = bool(engine) and await asyncio.to_thread(_database_ping, engine)

    limiter = getattr(request.app.state, "rate_limiter", None)
    redis_required = getattr(settings, "analysis_queue_backend", "in_process") == "rq"
    redis_ok = not redis_required
    if limiter is not None and redis_required:
        redis_ok = await limiter.ping()

    service = getattr(request.app.state, "analysis_service", None)
    queue_ok = service is not None
    worker_ok: bool | None = None
    if service is not None and hasattr(service, "healthcheck"):
        try:
            health = await service.healthcheck()
            if isinstance(health, dict):
                queue_ok = bool(health.get("queue", health.get("ready", False)))
                raw_worker = health.get("worker")
                worker_ok = bool(raw_worker) if raw_worker is not None else None
            else:
                queue_ok = bool(health)
        except Exception:
            queue_ok = False
            worker_ok = False

    registry = getattr(request.app.state, "method_registry", None)
    lreca_status = "unavailable"
    seg_status = "unavailable"
    if registry is not None:
        try:
            descriptors = {item.id: item for item in await registry.list_methods()}
            lreca_status = (
                "ready"
                if getattr(descriptors.get("lreca"), "automatic_analysis_available", False)
                else "unavailable"
            )
            seg_status = (
                "ready"
                if getattr(descriptors.get("seg"), "automatic_analysis_available", False)
                else "unavailable"
            )
        except Exception:
            pass

    production = getattr(settings, "environment", "development") == "production"
    ready = database_ok and queue_ok and (redis_ok if production else True)
    if production and worker_ok is not None:
        ready = ready and worker_ok
    if production:
        ready = ready and lreca_status == "ready" and seg_status == "ready"
    components = {
        "database": ComponentStatus(
            status="ready" if database_ok else "unavailable",
            mode="postgresql" if production else "development_database",
        ),
        "redis": ComponentStatus(
            status=("ready" if redis_ok else "unavailable")
            if redis_required
            else "not_applicable",
            mode="durable_queue" if redis_required else "local_development",
        ),
        "queue": ComponentStatus(
            status="ready" if queue_ok else "unavailable",
            mode="redis" if redis_required else "in_process_development",
        ),
        "worker": ComponentStatus(
            status=("ready" if worker_ok else "unavailable")
            if worker_ok is not None
            else "not_applicable",
            mode="separate_process" if redis_required else "in_process_development",
        ),
        "lreca": ComponentStatus(status=lreca_status, mode="human_specific_checkpoint"),
        "seg": ComponentStatus(status=seg_status, mode="annotation_only"),
        "fuzdrop": ComponentStatus(status="ready", mode="manual_import_only"),
        "dismeta": ComponentStatus(status="blocked", mode="integration_blocked"),
    }
    return SystemStatusResponse(ready=ready, components=components)


@router.get("/status", response_model=SystemStatusResponse)
async def system_status(request: Request) -> SystemStatusResponse:
    return await deployment_status(request)


@version_router.get("/version", response_model=VersionResponse)
async def system_version(request: Request) -> VersionResponse:
    settings = request.app.state.settings
    return VersionResponse(
        lreca={
            "model": "human-specific LRECA",
            "repository_commit": LRECA_REPOSITORY_COMMIT,
            "checkpoint": CHECKPOINT_NAME,
            "checkpoint_sha256": CHECKPOINT_SHA256,
        },
        seg={
            "implementation": "NCBI segmasker",
            "version": "2.17.0",
            "window": settings.seg_window,
            "locut": settings.seg_locut,
            "hicut": settings.seg_hicut,
        },
        fuzdrop={"mode": "manual_import"},
        dismeta={"mode": "blocked"},
        ensemble={
            "status": "experimental_uncalibrated",
            "threshold": settings.ensemble_threshold,
        },
    )

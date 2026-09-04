from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.api.lreca import READY_STATUSES, get_lreca_health
from app.api.system import deployment_status

router = APIRouter(tags=["health"])
ops_router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__
    module: Literal[10] = 10
    analysis_enabled: bool = False


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Service liveness is not scientific model readiness."""
    model_health = await get_lreca_health(request)
    return HealthResponse(analysis_enabled=model_health.status in READY_STATUSES)


@ops_router.get("/live")
async def live() -> dict[str, str | bool]:
    """Process liveness intentionally does not depend on models or infrastructure."""
    return {"status": "live", "live": True, "service": "llps-backend"}


@ops_router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness covers the database, queue path, and production Redis dependency."""
    status = await deployment_status(request)
    return JSONResponse(
        status_code=200 if status.ready else 503,
        content={
            "status": "ready" if status.ready else "not_ready",
            "ready": status.ready,
            "service": status.service,
            "components": {
                name: component.model_dump(mode="json")
                for name, component in status.components.items()
            },
        },
    )

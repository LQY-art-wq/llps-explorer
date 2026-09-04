"""Small public configuration allowlist for UI behavior."""

from fastapi import APIRouter, Request

from app.schemas.persistence import PublicConfig

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/public", response_model=PublicConfig)
async def public_config(request: Request) -> PublicConfig:
    return PublicConfig(analysis_retention_days=request.app.state.settings.analysis_retention_days)

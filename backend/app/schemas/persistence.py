"""Public persistence, history, and retention contracts."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.analysis import MethodId
from app.schemas.orchestration import JobStatus, PredictionMode


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    sequence_name: str | None
    sequence_length: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None
    expires_at: AwareDatetime
    status: JobStatus
    selected_methods: list[MethodId]
    prediction_mode: PredictionMode
    lreca_score: float | None = None
    fuzdrop_score: float | None = None
    ensemble_score: float | None = None
    result_schema_version: Literal["1.0"] = "1.0"


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[HistoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class PublicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_retention_days: int = Field(ge=1, le=3650)

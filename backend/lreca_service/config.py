"""Environment-only configuration for the internal LRECA service."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from lreca_runtime.metadata import (
    CHECKPOINT_RELATIVE_PATH,
    CHECKPOINT_SHA256,
    PROJECT_ROOT,
)


class LRECAServiceSettings(BaseSettings):
    """Configuration shared with ``LRECAAdapter`` without app/database settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    structured_logging: bool = Field(default=False, validation_alias="STRUCTURED_LOGGING")
    lreca_checkpoint: Path = Field(
        default=PROJECT_ROOT / "external" / "lreca" / CHECKPOINT_RELATIVE_PATH,
        validation_alias="LRECA_CHECKPOINT_PATH",
    )
    lreca_expected_checkpoint_sha256: str = Field(
        default=CHECKPOINT_SHA256,
        pattern=r"^[0-9a-f]{64}$",
        validation_alias="LRECA_CHECKPOINT_SHA256",
    )
    lreca_repository: Path = Field(
        default=PROJECT_ROOT / "external" / "lreca",
        validation_alias="LRECA_REPOSITORY",
    )
    lreca_python: Path = Field(
        default=Path(sys.executable), validation_alias="LRECA_PYTHON"
    )
    lreca_device: Literal["auto", "cpu", "cuda"] = Field(
        default="auto", validation_alias="LRECA_DEVICE"
    )
    lreca_classification_threshold: float = Field(
        default=0.5,
        ge=0,
        le=1,
        allow_inf_nan=False,
        validation_alias="LRECA_CLASSIFICATION_THRESHOLD",
    )
    lreca_top_residues: int = Field(
        default=10, ge=1, validation_alias="LRECA_TOP_RESIDUES"
    )
    lreca_kde_prominence: float = Field(
        default=0.1,
        ge=0,
        allow_inf_nan=False,
        validation_alias="LRECA_KDE_PROMINENCE",
    )
    lreca_torch_threads: int = Field(
        default=4, ge=1, le=64, validation_alias="LRECA_TORCH_THREADS"
    )
    lreca_worker_timeout_seconds: float = Field(
        default=120,
        gt=0,
        le=3600,
        allow_inf_nan=False,
        validation_alias="LRECA_WORKER_TIMEOUT_SECONDS",
    )
    lreca_startup_timeout_seconds: float = Field(
        default=120,
        gt=0,
        le=3600,
        allow_inf_nan=False,
        validation_alias="LRECA_STARTUP_TIMEOUT_SECONDS",
    )
    lreca_max_concurrent_requests: int = Field(
        default=1,
        ge=1,
        le=64,
        validation_alias="LRECA_MAX_CONCURRENT_REQUESTS",
    )
    lreca_model_processes: Literal[1] = Field(
        default=1,
        validation_alias="LRECA_MODEL_PROCESSES",
        description="One resident model process per service/GPU.",
    )
    analysis_max_sequence_length: int = Field(
        default=50000,
        ge=1,
        le=1000000,
        validation_alias="ANALYSIS_MAX_SEQUENCE_LENGTH",
    )

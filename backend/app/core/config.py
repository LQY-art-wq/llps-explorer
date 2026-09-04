import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lreca_runtime.metadata import CHECKPOINT_SHA256

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LRECA_REPOSITORY = PROJECT_ROOT / "external" / "lreca"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "backend" / "data" / "llps_explorer.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
LRECA_PYTHON = (
    PROJECT_ROOT
    / ".lreca-venv"
    / (Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python")
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "LLPS Explorer API"
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "LLPS_ENVIRONMENT"),
    )
    session_secret: SecretStr = Field(
        default=SecretStr("development-only-session-secret-do-not-deploy"),
        validation_alias="SESSION_SECRET",
    )
    public_base_url: str = Field(
        default="http://localhost", validation_alias="PUBLIC_BASE_URL"
    )
    public_https: bool = Field(default=False, validation_alias="PUBLIC_HTTPS")
    session_cookie_secure: bool | None = Field(
        default=None, validation_alias="SESSION_COOKIE_SECURE"
    )
    session_cookie_samesite: Literal["lax", "strict"] = Field(
        default="lax", validation_alias="SESSION_COOKIE_SAMESITE"
    )
    cors_allowed_origins: str = Field(
        default="http://localhost,http://127.0.0.1:3000",
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    trust_proxy_headers: bool = Field(default=False, validation_alias="TRUST_PROXY_HEADERS")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    structured_logging: bool = Field(default=False, validation_alias="STRUCTURED_LOGGING")
    run_migrations_on_startup: bool = Field(
        default=True, validation_alias="RUN_MIGRATIONS_ON_STARTUP"
    )
    rate_limit_window_seconds: int = Field(
        default=60, ge=1, le=86400, validation_alias="RATE_LIMIT_WINDOW_SECONDS"
    )
    rate_limit_analysis_requests: int = Field(
        default=10, ge=1, le=100000, validation_alias="RATE_LIMIT_ANALYSIS_REQUESTS"
    )
    rate_limit_import_requests: int = Field(
        default=10, ge=1, le=100000, validation_alias="RATE_LIMIT_IMPORT_REQUESTS"
    )
    rate_limit_delete_requests: int = Field(
        default=30, ge=1, le=100000, validation_alias="RATE_LIMIT_DELETE_REQUESTS"
    )
    rate_limit_export_requests: int = Field(
        default=60, ge=1, le=100000, validation_alias="RATE_LIMIT_EXPORT_REQUESTS"
    )
    rate_limit_ip_multiplier: int = Field(
        default=4, ge=1, le=100, validation_alias="RATE_LIMIT_IP_MULTIPLIER"
    )
    database_url: str = Field(default=DEFAULT_DATABASE_URL, validation_alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    analysis_queue_backend: Literal["in_process", "rq"] = Field(
        default="in_process", validation_alias="ANALYSIS_QUEUE_BACKEND"
    )
    analysis_queue_name: str = Field(
        default="analysis",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        validation_alias="ANALYSIS_QUEUE_NAME",
    )
    analysis_queue_max_jobs: int = Field(
        default=128, ge=1, le=10000, validation_alias="ANALYSIS_QUEUE_MAX_JOBS"
    )
    analysis_owner_active_job_limit: int = Field(
        default=4,
        ge=1,
        le=128,
        validation_alias="ANALYSIS_OWNER_ACTIVE_JOB_LIMIT",
    )
    analysis_queue_retry_max: int = Field(
        default=2, ge=1, le=10, validation_alias="ANALYSIS_QUEUE_RETRY_MAX"
    )
    analysis_queue_retry_interval_seconds: int = Field(
        default=10,
        ge=0,
        le=3600,
        validation_alias="ANALYSIS_QUEUE_RETRY_INTERVAL_SECONDS",
    )
    analysis_queue_ttl_seconds: int = Field(
        default=3600, ge=60, le=86400, validation_alias="ANALYSIS_QUEUE_TTL_SECONDS"
    )
    analysis_worker_recovery_timeout_seconds: int = Field(
        default=360,
        ge=60,
        le=86400,
        validation_alias="ANALYSIS_WORKER_RECOVERY_TIMEOUT_SECONDS",
    )
    analysis_worker_maintenance_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=600,
        validation_alias="ANALYSIS_WORKER_MAINTENANCE_INTERVAL_SECONDS",
    )
    analysis_retention_days: int = Field(
        default=7, ge=1, le=3650, validation_alias="ANALYSIS_RETENTION_DAYS"
    )
    analysis_cleanup_interval_seconds: float = Field(
        default=3600,
        gt=0,
        le=86400,
        allow_inf_nan=False,
        validation_alias="ANALYSIS_CLEANUP_INTERVAL_SECONDS",
    )
    dev_disable_job_ownership: bool = Field(
        default=False, validation_alias="DEV_DISABLE_JOB_OWNERSHIP"
    )
    lreca_python: Path = Field(default=LRECA_PYTHON, validation_alias="LRECA_PYTHON")
    lreca_checkpoint: Path = Field(
        default=LRECA_REPOSITORY / "Demo/trained_model/human_1_RCNN_ECA_parallel_089-0.9802.pt",
        validation_alias=AliasChoices("LRECA_CHECKPOINT_PATH", "LRECA_CHECKPOINT"),
    )
    lreca_repository: Path = Field(default=LRECA_REPOSITORY, validation_alias="LRECA_REPOSITORY")
    lreca_device: Literal["auto", "cpu", "cuda"] = Field(
        default="auto", validation_alias="LRECA_DEVICE"
    )
    lreca_service_url: str | None = Field(default=None, validation_alias="LRECA_SERVICE_URL")
    lreca_service_timeout_seconds: float = Field(
        default=150,
        gt=0,
        le=3600,
        allow_inf_nan=False,
        validation_alias="LRECA_SERVICE_TIMEOUT_SECONDS",
    )
    lreca_service_connect_timeout_seconds: float = Field(
        default=5,
        gt=0,
        le=60,
        allow_inf_nan=False,
        validation_alias="LRECA_SERVICE_CONNECT_TIMEOUT_SECONDS",
    )
    lreca_checkpoint_sha256: str = Field(
        default=CHECKPOINT_SHA256,
        pattern=r"^[0-9a-f]{64}$",
        validation_alias="LRECA_CHECKPOINT_SHA256",
    )
    lreca_classification_threshold: float = Field(
        default=0.5,
        ge=0,
        le=1,
        allow_inf_nan=False,
        validation_alias="LRECA_CLASSIFICATION_THRESHOLD",
    )
    lreca_top_residues: int = Field(default=10, ge=1, validation_alias="LRECA_TOP_RESIDUES")
    lreca_kde_prominence: float = Field(
        default=0.1, ge=0, allow_inf_nan=False, validation_alias="LRECA_KDE_PROMINENCE"
    )
    lreca_torch_threads: int = Field(default=4, ge=1, validation_alias="LRECA_TORCH_THREADS")
    lreca_worker_timeout_seconds: float = Field(
        default=120, gt=0, allow_inf_nan=False, validation_alias="LRECA_WORKER_TIMEOUT_SECONDS"
    )
    lreca_startup_timeout_seconds: float = Field(
        default=120, gt=0, allow_inf_nan=False, validation_alias="LRECA_STARTUP_TIMEOUT_SECONDS"
    )
    fuzdrop_official_site_url: Literal[
        "https://fuzdrop.bio.unipd.it",
        "https://fuzdrop.bio.unipd.it/",
        "https://fuzdrop.bio.unipd.it/predictor",
    ] = Field(
        default="https://fuzdrop.bio.unipd.it/predictor",
        validation_alias="FUZDROP_OFFICIAL_SITE_URL",
    )
    fuzdrop_manual_import_enabled: bool = Field(
        default=True, validation_alias="FUZDROP_MANUAL_IMPORT_ENABLED"
    )
    fuzdrop_import_max_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=1,
        validation_alias="FUZDROP_IMPORT_MAX_BYTES",
        description="Maximum local import payload bytes; not a scientific sequence-length limit.",
    )
    seg_executable_path: Path = Field(
        default=Path("segmasker"), validation_alias="SEG_EXECUTABLE_PATH"
    )
    seg_window: int = Field(default=12, ge=1, le=2147483647, validation_alias="SEG_WINDOW")
    seg_locut: float = Field(default=2.2, ge=0, allow_inf_nan=False, validation_alias="SEG_LOCUT")
    seg_hicut: float = Field(default=2.5, ge=0, allow_inf_nan=False, validation_alias="SEG_HICUT")
    seg_timeout_seconds: float = Field(
        default=10, gt=0, allow_inf_nan=False, validation_alias="SEG_TIMEOUT_SECONDS"
    )
    dismeta_official_site_url: Literal[
        "https://montelionelab.chem.rpi.edu/dismeta/",
        "https://montelionelab.chem.rpi.edu/dismeta",
    ] = Field(
        default="https://montelionelab.chem.rpi.edu/dismeta/",
        validation_alias="DISMETA_OFFICIAL_SITE_URL",
    )
    ensemble_threshold: float = Field(
        default=0.5, ge=0, le=1, allow_inf_nan=False, validation_alias="ENSEMBLE_THRESHOLD"
    )
    analysis_method_timeout_seconds: float = Field(
        default=150,
        gt=0,
        le=3600,
        allow_inf_nan=False,
        validation_alias="ANALYSIS_METHOD_TIMEOUT_SECONDS",
    )
    analysis_job_timeout_seconds: float = Field(
        default=180,
        gt=0,
        le=86400,
        allow_inf_nan=False,
        validation_alias="ANALYSIS_JOB_TIMEOUT_SECONDS",
    )
    analysis_job_ttl_seconds: float = Field(
        default=3600,
        ge=1e-6,
        le=86400,
        allow_inf_nan=False,
        validation_alias="ANALYSIS_JOB_TTL_SECONDS",
    )
    analysis_max_jobs: int = Field(
        default=128, ge=1, le=10000, validation_alias="ANALYSIS_MAX_JOBS"
    )
    analysis_max_concurrent_jobs: int = Field(
        default=4, ge=1, le=128, validation_alias="ANALYSIS_MAX_CONCURRENT_JOBS"
    )
    analysis_max_sequence_length: int = Field(
        default=50000,
        ge=1,
        le=1000000,
        validation_alias="ANALYSIS_MAX_SEQUENCE_LENGTH",
    )
    external_result_ttl_seconds: float = Field(
        default=3600,
        ge=1e-6,
        le=86400,
        allow_inf_nan=False,
        validation_alias="EXTERNAL_RESULT_TTL_SECONDS",
    )
    external_result_max_entries: int = Field(
        default=128, ge=1, le=10000, validation_alias="EXTERNAL_RESULT_MAX_ENTRIES"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith(
            ("sqlite://", "postgresql://", "postgresql+psycopg://")
        ):
            raise ValueError("DATABASE_URL must use SQLite or PostgreSQL with psycopg")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        return value

    @field_validator("lreca_service_url")
    @classmethod
    def validate_lreca_service_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("LRECA_SERVICE_URL must use http:// or https://")
        return value.rstrip("/") if value is not None else None

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) origin without credentials")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_seg_threshold_order(self) -> "Settings":
        if self.seg_hicut < self.seg_locut:
            raise ValueError("SEG_HICUT must be greater than or equal to SEG_LOCUT.")
        if self.analysis_max_concurrent_jobs > self.analysis_max_jobs:
            raise ValueError("ANALYSIS_MAX_CONCURRENT_JOBS must not exceed ANALYSIS_MAX_JOBS.")
        if (
            self.analysis_queue_backend == "rq"
            and self.analysis_queue_max_jobs > self.analysis_max_jobs
        ):
            raise ValueError("ANALYSIS_QUEUE_MAX_JOBS must not exceed ANALYSIS_MAX_JOBS.")
        if (
            self.analysis_queue_backend == "rq"
            and self.analysis_owner_active_job_limit > self.analysis_queue_max_jobs
        ):
            raise ValueError(
                "ANALYSIS_OWNER_ACTIVE_JOB_LIMIT must not exceed ANALYSIS_QUEUE_MAX_JOBS."
            )
        if (
            self.analysis_worker_recovery_timeout_seconds
            <= self.analysis_job_timeout_seconds + 60
        ):
            raise ValueError(
                "ANALYSIS_WORKER_RECOVERY_TIMEOUT_SECONDS must exceed the RQ kill deadline."
            )
        if self.environment == "production" and self.dev_disable_job_ownership:
            raise ValueError("DEV_DISABLE_JOB_OWNERSHIP cannot be enabled in production.")
        if self.environment == "production":
            if self.analysis_queue_backend != "rq":
                raise ValueError("Production requires ANALYSIS_QUEUE_BACKEND=rq.")
            if self.redis_url is None:
                raise ValueError("Production requires REDIS_URL.")
            if self.lreca_service_url is None:
                raise ValueError("Production requires LRECA_SERVICE_URL.")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production requires an explicit PostgreSQL DATABASE_URL.")
            if "replace-with" in self.database_url or (
                self.redis_url is not None and "replace-with" in self.redis_url
            ):
                raise ValueError("Production database and Redis credentials must be replaced.")
            secret = self.session_secret.get_secret_value()
            if len(secret) < 32 or secret.startswith(("development-only", "replace-with")):
                raise ValueError("Production requires a strong SESSION_SECRET.")
            origins = {item.strip() for item in self.cors_allowed_origins.split(",")}
            if "*" in origins:
                raise ValueError("Production CORS_ALLOWED_ORIGINS cannot contain '*'.")
            if self.public_https and self.session_cookie_secure is False:
                raise ValueError("HTTPS production requires a Secure session cookie.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

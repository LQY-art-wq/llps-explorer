"""SQLAlchemy schema shared by SQLite development and PostgreSQL production."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Unicode,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class AnalysisJobRow(Base):
    __tablename__ = "analysis_jobs"

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_name: Mapped[str | None] = mapped_column(Unicode(128))
    sequence_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_sequence: Mapped[str] = mapped_column(Text, nullable=False)
    selected_methods: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prediction_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    weights: Mapped[dict[str, float] | None] = mapped_column(JSON)
    method_states: Mapped[dict] = mapped_column(JSON, nullable=False)
    ensemble_result: Mapped[dict | None] = mapped_column(JSON)
    normalized_results: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    lreca_score: Mapped[float | None] = mapped_column(Float)
    fuzdrop_score: Mapped[float | None] = mapped_column(Float)
    ensemble_score: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_analysis_jobs_owner_created", "owner_id", "created_at"),
        Index("ix_analysis_jobs_expires_at", "expires_at"),
        Index("ix_analysis_jobs_status", "status"),
    )


class ImportedResultRow(Base):
    __tablename__ = "imported_results"

    result_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_length: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    coordinate_provenance: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_imported_results_owner_created", "owner_id", "created_at"),
        Index("ix_imported_results_expires_at", "expires_at"),
    )


class JobImportRow(Base):
    __tablename__ = "analysis_job_imports"

    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("analysis_jobs.job_id", ondelete="CASCADE"), primary_key=True
    )
    result_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("imported_results.result_id", ondelete="CASCADE"), primary_key=True
    )


class JobMethodRow(Base):
    __tablename__ = "analysis_job_methods"

    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("analysis_jobs.job_id", ondelete="CASCADE"), primary_key=True
    )
    method: Mapped[str] = mapped_column(String(32), primary_key=True)

    __table_args__ = (Index("ix_analysis_job_methods_method", "method"),)


def normalize_database_url(database_url: str) -> str:
    # The common PostgreSQL URL is accepted while using the modern psycopg driver.
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def create_database_engine(database_url: str) -> Engine:
    url = normalize_database_url(database_url)
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, "", ":memory:"}:
        Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    options: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if url not in {"sqlite://", "sqlite:///:memory:"}:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine

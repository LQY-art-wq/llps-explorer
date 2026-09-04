"""Create persistent analysis, import, and ownership tables.

Revision ID: 20260904_0001
Revises:
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sequence_name", sa.Unicode(length=128), nullable=True),
        sa.Column("sequence_length", sa.Integer(), nullable=False),
        sa.Column("sequence_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalized_sequence", sa.Text(), nullable=False),
        sa.Column("selected_methods", sa.JSON(), nullable=False),
        sa.Column("prediction_mode", sa.String(length=32), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=True),
        sa.Column("method_states", sa.JSON(), nullable=False),
        sa.Column("ensemble_result", sa.JSON(), nullable=True),
        sa.Column("normalized_results", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("result_schema_version", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_analysis_jobs_owner_created", "analysis_jobs", ["owner_id", "created_at"]
    )
    op.create_index("ix_analysis_jobs_expires_at", "analysis_jobs", ["expires_at"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])

    op.create_table(
        "imported_results",
        sa.Column("result_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence_sha256", sa.String(length=64), nullable=False),
        sa.Column("sequence_length", sa.Integer(), nullable=False),
        sa.Column("normalized_result", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("coordinate_provenance", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index(
        "ix_imported_results_owner_created", "imported_results", ["owner_id", "created_at"]
    )
    op.create_index("ix_imported_results_expires_at", "imported_results", ["expires_at"])

    op.create_table(
        "analysis_job_imports",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("result_id", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["result_id"], ["imported_results.result_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", "result_id"),
    )


def downgrade() -> None:
    op.drop_table("analysis_job_imports")
    op.drop_index("ix_imported_results_expires_at", table_name="imported_results")
    op.drop_index("ix_imported_results_owner_created", table_name="imported_results")
    op.drop_table("imported_results")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_expires_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_owner_created", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")

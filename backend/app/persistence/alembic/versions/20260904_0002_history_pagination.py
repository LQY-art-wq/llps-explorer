"""Add lightweight history summary fields and relational method filtering.

Revision ID: 20260904_0002
Revises: 20260904_0001
Create Date: 2026-09-04
"""

import json

import sqlalchemy as sa
from alembic import context, op

revision = "20260904_0002"
down_revision = "20260904_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("lreca_score", sa.Float(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("fuzdrop_score", sa.Float(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("ensemble_score", sa.Float(), nullable=True))
    op.create_table(
        "analysis_job_methods",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "method"),
    )
    op.create_index(
        "ix_analysis_job_methods_method", "analysis_job_methods", ["method"], unique=False
    )

    # Alembic's offline mode has no live result set to iterate. Fresh databases
    # have no rows to backfill, while upgrades of an existing database must be
    # run online so the versioned JSON payload can be decoded portably on both
    # SQLite and PostgreSQL.
    if context.is_offline_mode():
        return

    connection = op.get_bind()
    methods_table = sa.table(
        "analysis_job_methods", sa.column("job_id", sa.String()), sa.column("method", sa.String())
    )
    jobs_table = sa.table(
        "analysis_jobs",
        sa.column("job_id", sa.String()),
        sa.column("lreca_score", sa.Float()),
        sa.column("fuzdrop_score", sa.Float()),
        sa.column("ensemble_score", sa.Float()),
    )
    rows = connection.execute(
        sa.text("SELECT job_id, selected_methods, result_payload FROM analysis_jobs")
    ).mappings()
    for row in rows:
        selected = row["selected_methods"]
        payload = row["result_payload"]
        if isinstance(selected, str):
            selected = json.loads(selected)
        if isinstance(payload, str):
            payload = json.loads(payload)
        for method in selected or []:
            connection.execute(methods_table.insert().values(job_id=row["job_id"], method=method))
        methods = (payload or {}).get("methods", {})

        def score(method: str):
            return ((methods.get(method) or {}).get("result") or {}).get("raw_score")

        ensemble = (payload or {}).get("ensemble") or {}
        connection.execute(
            jobs_table.update()
            .where(jobs_table.c.job_id == row["job_id"])
            .values(
                lreca_score=score("lreca"),
                fuzdrop_score=score("fuzdrop"),
                ensemble_score=ensemble.get("score"),
            )
        )


def downgrade() -> None:
    op.drop_index("ix_analysis_job_methods_method", table_name="analysis_job_methods")
    op.drop_table("analysis_job_methods")
    op.drop_column("analysis_jobs", "ensemble_score")
    op.drop_column("analysis_jobs", "fuzdrop_score")
    op.drop_column("analysis_jobs", "lreca_score")

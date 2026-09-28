"""Persist version-bound result snapshots.

Revision ID: 0003_saved_results
Revises: 0002_job_artifact_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_saved_results"
down_revision: str | None = "0002_job_artifact_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="RESTRICT")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "fingerprint", name="result_version_fingerprint"),
    )
    op.create_index(
        "ix_saved_results_version_created", "saved_results", ["dataset_version_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_saved_results_version_created", table_name="saved_results")
    op.drop_table("saved_results")

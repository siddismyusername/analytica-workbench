"""Enforce idempotent per-job artifact registration.

Revision ID: 0002_job_artifact_idempotency
Revises: 0001_control_plane
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_job_artifact_idempotency"
down_revision: str | None = "0001_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.create_unique_constraint(
            "uq_artifacts_job_artifact_kind",
            ["job_id", "kind"],
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.drop_constraint("uq_artifacts_job_artifact_kind", type_="unique")

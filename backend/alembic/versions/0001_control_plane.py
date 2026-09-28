from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_control_plane"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("next_version_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("next_version_number >= 1", name="ck_datasets_next_version_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source_format", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("schema_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_number >= 1", name="ck_dataset_versions_version_positive"),
        sa.CheckConstraint("row_count >= 0", name="ck_dataset_versions_row_count_nonnegative"),
        sa.CheckConstraint("byte_size >= 0", name="ck_dataset_versions_byte_size_nonnegative"),
        sa.CheckConstraint(
            "state IN ('pending', 'ready', 'failed')",
            name="ck_dataset_versions_state",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name="fk_dataset_versions_dataset_id_datasets"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["dataset_versions.id"],
            name="fk_dataset_versions_parent_version_id_dataset_versions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_versions"),
        sa.UniqueConstraint(
            "dataset_id", "version_number", name="uq_dataset_versions_dataset_version_number"
        ),
    )
    op.create_index(
        "ix_dataset_versions_dataset_created",
        "dataset_versions",
        ["dataset_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("input_version_id", sa.Uuid(), nullable=True),
        sa.Column("output_version_id", sa.Uuid(), nullable=True),
        sa.Column("operation_payload", sa.JSON(), nullable=False),
        sa.Column("error_detail", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count_nonnegative"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name="fk_jobs_dataset_id_datasets"
        ),
        sa.ForeignKeyConstraint(
            ["input_version_id"],
            ["dataset_versions.id"],
            name="fk_jobs_input_version_id_dataset_versions",
        ),
        sa.ForeignKeyConstraint(
            ["output_version_id"],
            ["dataset_versions.id"],
            name="fk_jobs_output_version_id_dataset_versions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"], unique=False)
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_artifacts_byte_size_nonnegative"),
        sa.CheckConstraint(
            "dataset_version_id IS NOT NULL OR job_id IS NOT NULL",
            name="ck_artifacts_has_owner",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name="fk_artifacts_dataset_version_id_dataset_versions",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_artifacts_job_id_jobs"),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("storage_key", name="uq_artifacts_storage_key"),
        sa.UniqueConstraint(
            "dataset_version_id", "kind", name="uq_artifacts_dataset_version_artifact_kind"
        ),
    )
    op.create_index("ix_artifacts_job_kind", "artifacts", ["job_id", "kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_artifacts_job_kind", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_jobs_status_created", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_dataset_versions_dataset_created", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")

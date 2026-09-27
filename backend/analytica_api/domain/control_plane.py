from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DatasetVersionState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    next_version_number: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class DatasetVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    dataset_id: UUID
    version_number: int = Field(ge=1)
    parent_version_id: UUID | None
    state: DatasetVersionState
    source_format: str
    row_count: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    schema_snapshot: dict[str, Any]
    created_at: datetime


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    dataset_version_id: UUID | None
    job_id: UUID | None
    kind: str
    storage_key: str
    content_type: str
    byte_size: int = Field(ge=0)
    checksum_sha256: str | None
    created_at: datetime


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    kind: str
    status: JobStatus
    idempotency_key: str
    dataset_id: UUID | None
    input_version_id: UUID | None
    output_version_id: UUID | None
    operation_payload: dict[str, Any]
    error_detail: dict[str, Any] | None
    attempt_count: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

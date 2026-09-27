from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from analytica_api.domain.control_plane import (
    ArtifactRecord,
    DatasetRecord,
    DatasetVersionRecord,
    DatasetVersionState,
    JobRecord,
    JobStatus,
)
from analytica_api.ingestion.models import IngestionManifest
from analytica_api.persistence.unit_of_work import UnitOfWork
from analytica_api.storage.contracts import StorageObjectRef


class ControlPlaneError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisteredDatasetVersion:
    version: DatasetVersionRecord
    artifact: ArtifactRecord


_ALLOWED_JOB_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class ControlPlaneService:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]):
        self.unit_of_work_factory = unit_of_work_factory

    def create_dataset(self, name: str) -> DatasetRecord:
        normalized = name.strip()
        if not normalized:
            raise ControlPlaneError("dataset name cannot be empty")

        with self.unit_of_work_factory() as unit_of_work:
            dataset = unit_of_work.datasets.create(name=normalized)
            unit_of_work.commit()
            return dataset

    def register_ingested_version(
        self,
        *,
        dataset_id: UUID,
        manifest: IngestionManifest,
        object_ref: StorageObjectRef,
        parent_version_id: UUID | None = None,
    ) -> RegisteredDatasetVersion:
        if manifest.byte_size != object_ref.byte_size:
            raise ControlPlaneError("artifact size does not match the ingestion manifest")

        with self.unit_of_work_factory() as unit_of_work:
            if unit_of_work.datasets.get(dataset_id) is None:
                raise ControlPlaneError(f"dataset does not exist: {dataset_id}")

            if parent_version_id is not None:
                parent = unit_of_work.versions.get(parent_version_id)
                if parent is None or parent.dataset_id != dataset_id:
                    raise ControlPlaneError("parent version must belong to the same dataset")

            version_number = unit_of_work.datasets.allocate_next_version_number(dataset_id)
            version = unit_of_work.versions.create(
                dataset_id=dataset_id,
                version_number=version_number,
                parent_version_id=parent_version_id,
                state=DatasetVersionState.READY,
                source_format=manifest.source_format,
                row_count=manifest.row_count,
                byte_size=manifest.byte_size,
                schema_snapshot=manifest.schema.model_dump(mode="json"),
            )
            artifact = unit_of_work.artifacts.create(
                dataset_version_id=version.id,
                job_id=None,
                kind="canonical_dataset",
                object_ref=object_ref,
            )
            unit_of_work.commit()
            return RegisteredDatasetVersion(version=version, artifact=artifact)

    def create_job(
        self,
        *,
        kind: str,
        idempotency_key: str,
        dataset_id: UUID | None = None,
        input_version_id: UUID | None = None,
        operation_payload: dict[str, Any] | None = None,
    ) -> JobRecord:
        normalized_kind = kind.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_kind or not normalized_key:
            raise ControlPlaneError("job kind and idempotency key are required")

        with self.unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.jobs.get_by_idempotency_key(normalized_key)
            if existing is not None:
                return existing
            job = unit_of_work.jobs.create(
                kind=normalized_kind,
                idempotency_key=normalized_key,
                dataset_id=dataset_id,
                input_version_id=input_version_id,
                operation_payload=operation_payload or {},
            )
            unit_of_work.commit()
            return job

    def transition_job(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        error_detail: dict[str, Any] | None = None,
        output_version_id: UUID | None = None,
    ) -> JobRecord:
        with self.unit_of_work_factory() as unit_of_work:
            current = unit_of_work.jobs.get(job_id)
            if current is None:
                raise ControlPlaneError(f"job does not exist: {job_id}")
            if status not in _ALLOWED_JOB_TRANSITIONS[current.status]:
                raise ControlPlaneError(
                    f"invalid job transition: {current.status.value} -> {status.value}"
                )
            updated = unit_of_work.jobs.update_status(
                job_id,
                status=status,
                error_detail=error_detail,
                output_version_id=output_version_id,
            )
            if updated is None:
                raise ControlPlaneError(f"job does not exist: {job_id}")
            unit_of_work.commit()
            return updated

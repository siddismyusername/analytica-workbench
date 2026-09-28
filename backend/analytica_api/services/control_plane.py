from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from analytica_api.domain.control_plane import (
    ArtifactRecord,
    DatasetRecord,
    DatasetVersionRecord,
    DatasetVersionState,
    JobRecord,
    JobStatus,
    SavedResultRecord,
)
from analytica_api.domain.datasets import DatasetSchema
from analytica_api.ingestion.models import IngestionManifest, SourceFormat
from analytica_api.persistence.unit_of_work import UnitOfWork
from analytica_api.storage.contracts import StorageObjectRef


class ControlPlaneError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisteredDatasetVersion:
    version: DatasetVersionRecord
    artifact: ArtifactRecord


@dataclass(frozen=True)
class CreatedIngestionJob:
    dataset: DatasetRecord
    job: JobRecord
    raw_artifact: ArtifactRecord


_ALLOWED_JOB_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: {JobStatus.RUNNING, JobStatus.CANCELLED},
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

    def get_dataset(self, dataset_id: UUID) -> DatasetRecord:
        with self.unit_of_work_factory() as unit_of_work:
            dataset = unit_of_work.datasets.get(dataset_id)
            if dataset is None:
                raise ControlPlaneError(f"dataset does not exist: {dataset_id}")
            return dataset

    def get_version(self, version_id: UUID) -> DatasetVersionRecord:
        with self.unit_of_work_factory() as unit_of_work:
            version = unit_of_work.versions.get(version_id)
            if version is None:
                raise ControlPlaneError(f"dataset version does not exist: {version_id}")
            return version

    def get_job(self, job_id: UUID) -> JobRecord:
        with self.unit_of_work_factory() as unit_of_work:
            job = unit_of_work.jobs.get(job_id)
            if job is None:
                raise ControlPlaneError(f"job does not exist: {job_id}")
            return job

    def get_job_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.jobs.get_by_idempotency_key(idempotency_key.strip())

    def get_job_by_output_version_id(self, version_id: UUID) -> JobRecord | None:
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.jobs.get_by_output_version_id(version_id)

    def list_jobs_for_version(self, version_id: UUID, kind: str) -> tuple[JobRecord, ...]:
        self.get_version(version_id)
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.jobs.list_for_input_version(version_id, kind)

    def register_job_artifact(
        self, *, job_id: UUID, kind: str, object_ref: StorageObjectRef
    ) -> ArtifactRecord:
        with self.unit_of_work_factory() as unit_of_work:
            job = unit_of_work.jobs.get(job_id)
            if job is None:
                raise ControlPlaneError(f"job does not exist: {job_id}")
            existing = unit_of_work.artifacts.get_for_job_kind(job_id, kind)
            if existing is not None:
                if existing.storage_key != object_ref.key:
                    raise ControlPlaneError("job artifact key changed on retry")
                return existing
            artifact = unit_of_work.artifacts.create(
                dataset_version_id=None,
                job_id=job_id,
                kind=kind,
                object_ref=object_ref,
            )
            unit_of_work.commit()
            return artifact

    def get_artifact_for_version_kind(self, version_id: UUID, kind: str) -> ArtifactRecord:
        with self.unit_of_work_factory() as unit_of_work:
            artifact = unit_of_work.artifacts.get_for_version_kind(version_id, kind)
            if artifact is None:
                raise ControlPlaneError(f"artifact does not exist for version {version_id}: {kind}")
            return artifact

    def get_artifact_for_job_kind(self, job_id: UUID, kind: str) -> ArtifactRecord:
        with self.unit_of_work_factory() as unit_of_work:
            artifact = unit_of_work.artifacts.get_for_job_kind(job_id, kind)
            if artifact is None:
                raise ControlPlaneError(f"artifact does not exist for job {job_id}: {kind}")
            return artifact

    def get_artifact(self, artifact_id: UUID) -> ArtifactRecord:
        with self.unit_of_work_factory() as unit_of_work:
            artifact = unit_of_work.artifacts.get(artifact_id)
            if artifact is None:
                raise ControlPlaneError(f"artifact does not exist: {artifact_id}")
            return artifact

    def save_result(
        self,
        *,
        version_id: UUID,
        kind: str,
        title: str,
        fingerprint: str,
        configuration: dict[str, Any],
        payload: dict[str, Any],
        source_job_id: UUID | None = None,
    ) -> SavedResultRecord:
        try:
            with self.unit_of_work_factory() as unit_of_work:
                version = unit_of_work.versions.get(version_id)
                if version is None or version.state != DatasetVersionState.READY:
                    raise ControlPlaneError("saved results require a ready dataset version")
                if source_job_id is not None:
                    job = unit_of_work.jobs.get(source_job_id)
                    if job is None or job.input_version_id != version_id:
                        raise ControlPlaneError("result job must belong to the same version")
                existing = unit_of_work.results.get_by_fingerprint(version_id, fingerprint)
                if existing is not None:
                    return existing
                result = unit_of_work.results.create(
                    dataset_version_id=version_id,
                    source_job_id=source_job_id,
                    kind=kind,
                    title=title[:255],
                    fingerprint=fingerprint,
                    configuration=configuration,
                    payload=payload,
                )
                unit_of_work.commit()
                return result
        except IntegrityError:
            with self.unit_of_work_factory() as unit_of_work:
                existing = unit_of_work.results.get_by_fingerprint(version_id, fingerprint)
                if existing is not None:
                    return existing
            raise

    def list_results(self, version_id: UUID) -> tuple[SavedResultRecord, ...]:
        self.get_version(version_id)
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.results.list_for_version(version_id)

    def get_result(self, result_id: UUID) -> SavedResultRecord:
        with self.unit_of_work_factory() as unit_of_work:
            result = unit_of_work.results.get(result_id)
            if result is None:
                raise ControlPlaneError(f"saved result does not exist: {result_id}")
            return result

    def create_ingestion_job(
        self,
        *,
        dataset_name: str,
        source_format: SourceFormat,
        source_ref: StorageObjectRef,
        idempotency_key: str,
    ) -> CreatedIngestionJob:
        normalized_name = dataset_name.strip()
        normalized_key = idempotency_key.strip()
        if not normalized_name:
            raise ControlPlaneError("dataset name cannot be empty")
        if not normalized_key:
            raise ControlPlaneError("idempotency key cannot be empty")

        with self.unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.jobs.get_by_idempotency_key(normalized_key)
            if existing is not None:
                if existing.kind != "ingest" or existing.dataset_id is None:
                    raise ControlPlaneError("idempotency key belongs to another operation")
                dataset = unit_of_work.datasets.get(existing.dataset_id)
                raw_artifact = unit_of_work.artifacts.get_for_job_kind(existing.id, "raw_upload")
                if dataset is None or raw_artifact is None:
                    raise ControlPlaneError("existing ingestion job is incomplete")
                original_format = existing.operation_payload.get("source_format")
                if (
                    original_format != source_format
                    or raw_artifact.storage_key != source_ref.key
                    or raw_artifact.byte_size != source_ref.byte_size
                ):
                    raise ControlPlaneError(
                        "idempotency key was already used with different upload data"
                    )
                return CreatedIngestionJob(dataset=dataset, job=existing, raw_artifact=raw_artifact)

            dataset = unit_of_work.datasets.create(name=normalized_name)
            job = unit_of_work.jobs.create(
                kind="ingest",
                idempotency_key=normalized_key,
                dataset_id=dataset.id,
                input_version_id=None,
                operation_payload={"source_format": source_format},
            )
            raw_artifact = unit_of_work.artifacts.create(
                dataset_version_id=None,
                job_id=job.id,
                kind="raw_upload",
                object_ref=source_ref,
            )
            unit_of_work.commit()
            return CreatedIngestionJob(dataset=dataset, job=job, raw_artifact=raw_artifact)

    def register_ingested_version(
        self,
        *,
        dataset_id: UUID,
        manifest: IngestionManifest,
        object_ref: StorageObjectRef,
        parent_version_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> RegisteredDatasetVersion:
        if manifest.byte_size != object_ref.byte_size:
            raise ControlPlaneError("artifact size does not match the ingestion manifest")
        return self._register_version(
            dataset_id=dataset_id,
            parent_version_id=parent_version_id,
            schema=manifest.schema,
            row_count=manifest.row_count,
            object_ref=object_ref,
            job_id=job_id,
            source_format=manifest.source_format,
        )

    def register_derived_version(
        self,
        *,
        dataset_id: UUID,
        parent_version_id: UUID,
        schema: DatasetSchema,
        row_count: int,
        object_ref: StorageObjectRef,
        job_id: UUID,
    ) -> RegisteredDatasetVersion:
        return self._register_version(
            dataset_id=dataset_id,
            parent_version_id=parent_version_id,
            schema=schema,
            row_count=row_count,
            object_ref=object_ref,
            job_id=job_id,
            source_format="parquet",
        )

    def _register_version(
        self,
        *,
        dataset_id: UUID,
        parent_version_id: UUID | None,
        schema: DatasetSchema,
        row_count: int,
        object_ref: StorageObjectRef,
        job_id: UUID | None,
        source_format: str,
    ) -> RegisteredDatasetVersion:
        with self.unit_of_work_factory() as unit_of_work:
            if unit_of_work.datasets.get(dataset_id) is None:
                raise ControlPlaneError(f"dataset does not exist: {dataset_id}")

            if job_id is not None:
                job = unit_of_work.jobs.get(job_id)
                if job is None or job.dataset_id != dataset_id:
                    raise ControlPlaneError("job must belong to the same dataset")
                existing_artifact = unit_of_work.artifacts.get_for_job_kind(
                    job_id, "canonical_dataset"
                )
                if existing_artifact is not None:
                    if existing_artifact.dataset_version_id is None:
                        raise ControlPlaneError("canonical artifact is missing its dataset version")
                    existing_version = unit_of_work.versions.get(
                        existing_artifact.dataset_version_id
                    )
                    if existing_version is None:
                        raise ControlPlaneError("canonical artifact references a missing version")
                    return RegisteredDatasetVersion(
                        version=existing_version,
                        artifact=existing_artifact,
                    )

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
                source_format=source_format,
                row_count=row_count,
                byte_size=object_ref.byte_size,
                schema_snapshot=schema.model_dump(mode="json"),
            )
            artifact = unit_of_work.artifacts.create(
                dataset_version_id=version.id,
                job_id=job_id,
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

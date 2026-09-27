from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from analytica_api.domain.control_plane import (
    ArtifactRecord,
    DatasetRecord,
    DatasetVersionRecord,
    DatasetVersionState,
    JobRecord,
    JobStatus,
)
from analytica_api.persistence.models import (
    ArtifactModel,
    DatasetModel,
    DatasetVersionModel,
    JobModel,
    utc_now,
)
from analytica_api.storage.contracts import StorageObjectRef


class DatasetRepository(Protocol):
    def create(self, *, name: str) -> DatasetRecord: ...

    def get(self, dataset_id: UUID) -> DatasetRecord | None: ...

    def allocate_next_version_number(self, dataset_id: UUID) -> int: ...


class DatasetVersionRepository(Protocol):
    def create(
        self,
        *,
        dataset_id: UUID,
        version_number: int,
        parent_version_id: UUID | None,
        state: DatasetVersionState,
        source_format: str,
        row_count: int,
        byte_size: int,
        schema_snapshot: dict[str, Any],
    ) -> DatasetVersionRecord: ...

    def get(self, version_id: UUID) -> DatasetVersionRecord | None: ...


class ArtifactRepository(Protocol):
    def create(
        self,
        *,
        dataset_version_id: UUID | None,
        job_id: UUID | None,
        kind: str,
        object_ref: StorageObjectRef,
    ) -> ArtifactRecord: ...

    def get_for_version_kind(self, version_id: UUID, kind: str) -> ArtifactRecord | None: ...

    def get_for_job_kind(self, job_id: UUID, kind: str) -> ArtifactRecord | None: ...


class JobRepository(Protocol):
    def create(
        self,
        *,
        kind: str,
        idempotency_key: str,
        dataset_id: UUID | None,
        input_version_id: UUID | None,
        operation_payload: dict[str, Any],
    ) -> JobRecord: ...

    def get(self, job_id: UUID) -> JobRecord | None: ...

    def get_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None: ...

    def update_status(
        self,
        job_id: UUID,
        *,
        status: JobStatus,
        error_detail: dict[str, Any] | None = None,
        output_version_id: UUID | None = None,
    ) -> JobRecord | None: ...


def _dataset_record(model: DatasetModel) -> DatasetRecord:
    return DatasetRecord(
        id=model.id,
        name=model.name,
        next_version_number=model.next_version_number,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _version_record(model: DatasetVersionModel) -> DatasetVersionRecord:
    return DatasetVersionRecord(
        id=model.id,
        dataset_id=model.dataset_id,
        version_number=model.version_number,
        parent_version_id=model.parent_version_id,
        state=DatasetVersionState(model.state),
        source_format=model.source_format,
        row_count=model.row_count,
        byte_size=model.byte_size,
        schema_snapshot=model.schema_snapshot,
        created_at=model.created_at,
    )


def _artifact_record(model: ArtifactModel) -> ArtifactRecord:
    return ArtifactRecord(
        id=model.id,
        dataset_version_id=model.dataset_version_id,
        job_id=model.job_id,
        kind=model.kind,
        storage_key=model.storage_key,
        content_type=model.content_type,
        byte_size=model.byte_size,
        checksum_sha256=model.checksum_sha256,
        created_at=model.created_at,
    )


def _job_record(model: JobModel) -> JobRecord:
    return JobRecord(
        id=model.id,
        kind=model.kind,
        status=JobStatus(model.status),
        idempotency_key=model.idempotency_key,
        dataset_id=model.dataset_id,
        input_version_id=model.input_version_id,
        output_version_id=model.output_version_id,
        operation_payload=model.operation_payload,
        error_detail=model.error_detail,
        attempt_count=model.attempt_count,
        created_at=model.created_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


class SqlAlchemyDatasetRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, name: str) -> DatasetRecord:
        model = DatasetModel(name=name)
        self.session.add(model)
        self.session.flush()
        return _dataset_record(model)

    def get(self, dataset_id: UUID) -> DatasetRecord | None:
        model = self.session.get(DatasetModel, dataset_id)
        return _dataset_record(model) if model else None

    def allocate_next_version_number(self, dataset_id: UUID) -> int:
        statement = select(DatasetModel).where(DatasetModel.id == dataset_id).with_for_update()
        model = self.session.execute(statement).scalar_one_or_none()
        if model is None:
            raise LookupError(f"dataset does not exist: {dataset_id}")
        version_number = model.next_version_number
        model.next_version_number += 1
        self.session.flush()
        return version_number


class SqlAlchemyDatasetVersionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        dataset_id: UUID,
        version_number: int,
        parent_version_id: UUID | None,
        state: DatasetVersionState,
        source_format: str,
        row_count: int,
        byte_size: int,
        schema_snapshot: dict[str, Any],
    ) -> DatasetVersionRecord:
        model = DatasetVersionModel(
            dataset_id=dataset_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            state=state.value,
            source_format=source_format,
            row_count=row_count,
            byte_size=byte_size,
            schema_snapshot=schema_snapshot,
        )
        self.session.add(model)
        self.session.flush()
        return _version_record(model)

    def get(self, version_id: UUID) -> DatasetVersionRecord | None:
        model = self.session.get(DatasetVersionModel, version_id)
        return _version_record(model) if model else None


class SqlAlchemyArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        dataset_version_id: UUID | None,
        job_id: UUID | None,
        kind: str,
        object_ref: StorageObjectRef,
    ) -> ArtifactRecord:
        model = ArtifactModel(
            dataset_version_id=dataset_version_id,
            job_id=job_id,
            kind=kind,
            storage_key=object_ref.key,
            content_type=object_ref.content_type,
            byte_size=object_ref.byte_size,
            checksum_sha256=object_ref.checksum_sha256,
        )
        self.session.add(model)
        self.session.flush()
        return _artifact_record(model)

    def get_for_version_kind(self, version_id: UUID, kind: str) -> ArtifactRecord | None:
        statement = select(ArtifactModel).where(
            ArtifactModel.dataset_version_id == version_id,
            ArtifactModel.kind == kind,
        )
        model = self.session.execute(statement).scalar_one_or_none()
        return _artifact_record(model) if model else None

    def get_for_job_kind(self, job_id: UUID, kind: str) -> ArtifactRecord | None:
        statement = select(ArtifactModel).where(
            ArtifactModel.job_id == job_id,
            ArtifactModel.kind == kind,
        )
        model = self.session.execute(statement).scalar_one_or_none()
        return _artifact_record(model) if model else None


class SqlAlchemyJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        kind: str,
        idempotency_key: str,
        dataset_id: UUID | None,
        input_version_id: UUID | None,
        operation_payload: dict[str, Any],
    ) -> JobRecord:
        model = JobModel(
            kind=kind,
            status=JobStatus.QUEUED.value,
            idempotency_key=idempotency_key,
            dataset_id=dataset_id,
            input_version_id=input_version_id,
            operation_payload=operation_payload,
        )
        self.session.add(model)
        self.session.flush()
        return _job_record(model)

    def get(self, job_id: UUID) -> JobRecord | None:
        model = self.session.get(JobModel, job_id)
        return _job_record(model) if model else None

    def get_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        statement = select(JobModel).where(JobModel.idempotency_key == idempotency_key)
        model = self.session.execute(statement).scalar_one_or_none()
        return _job_record(model) if model else None

    def update_status(
        self,
        job_id: UUID,
        *,
        status: JobStatus,
        error_detail: dict[str, Any] | None = None,
        output_version_id: UUID | None = None,
    ) -> JobRecord | None:
        statement = select(JobModel).where(JobModel.id == job_id).with_for_update()
        model = self.session.execute(statement).scalar_one_or_none()
        if model is None:
            return None

        now: datetime = utc_now()
        model.status = status.value
        model.error_detail = error_detail
        if output_version_id is not None:
            model.output_version_id = output_version_id
        if status == JobStatus.RUNNING:
            model.started_at = model.started_at or now
            model.completed_at = None
            model.attempt_count += 1
        if status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
            model.completed_at = now
        self.session.flush()
        return _job_record(model)

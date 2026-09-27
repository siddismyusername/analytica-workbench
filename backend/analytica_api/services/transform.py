from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import duckdb
from pydantic import TypeAdapter

from analytica_api.domain.control_plane import JobRecord, JobStatus
from analytica_api.domain.datasets import DatasetSchema, DatasetSource
from analytica_api.execution.duckdb_engine import PipelineCompiler
from analytica_api.operations.models import Operation, PipelineSpec
from analytica_api.queue.contracts import JobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef

_OPERATION_ADAPTER = TypeAdapter(Operation)


@dataclass(frozen=True)
class TransformPreview:
    input_version_id: UUID
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    input_row_count: int
    output_row_count: int
    output_schema: DatasetSchema


@dataclass(frozen=True)
class TransformSubmission:
    job: JobRecord
    input_version_id: UUID


@dataclass(frozen=True)
class TransformHistoryItem:
    job_id: UUID
    input_version_id: UUID
    output_version_id: UUID
    output_version_number: int
    operation: dict[str, Any]
    created_at: str


def _object_ref_from_artifact(artifact: Any) -> StorageObjectRef:
    return StorageObjectRef(
        key=artifact.storage_key,
        byte_size=artifact.byte_size,
        content_type=artifact.content_type,
        checksum_sha256=artifact.checksum_sha256,
    )


def _idempotency_key(version_id: UUID, operation: Operation) -> str:
    payload = json.dumps(
        operation.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(f"{version_id}:{payload}".encode()).hexdigest()
    return f"transform:{digest}"


class DatasetTransformService:
    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
        job_queue: JobQueue,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store
        self.job_queue = job_queue

    def _version_context(self, version_id: UUID) -> tuple[Any, DatasetSchema, Any]:
        version = self.control_plane.get_version(version_id)
        schema = DatasetSchema.model_validate(version.schema_snapshot)
        artifact = self.control_plane.get_artifact_for_version_kind(
            version_id,
            "canonical_dataset",
        )
        return version, schema, artifact

    def preview(
        self,
        version_id: UUID,
        operation: Operation,
        *,
        limit: int = 50,
    ) -> TransformPreview:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        version, schema, artifact = self._version_context(version_id)
        pipeline = PipelineSpec(operations=(operation,))
        compiler = PipelineCompiler(schema)
        output_schema = compiler.evolve_schema(pipeline)

        with TemporaryDirectory(prefix="analytica-transform-preview-") as directory:
            path = self.artifact_store.materialize(
                _object_ref_from_artifact(artifact),
                Path(directory) / "input.parquet",
            )
            source = DatasetSource(uri=str(path))
            compiled = compiler.compile(source, pipeline, limit=limit)
            full_query = compiler.compile(source, pipeline)
            connection = duckdb.connect(database=":memory:")
            try:
                cursor = connection.execute(compiled.sql, compiled.parameters)
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(tuple(row) for row in cursor.fetchall())
                count_row = connection.execute(
                    f"SELECT COUNT(*) FROM ({full_query.sql}) AS transformed",
                    full_query.parameters,
                ).fetchone()
            finally:
                connection.close()
        output_count = int(count_row[0]) if count_row is not None else 0
        return TransformPreview(
            input_version_id=version.id,
            columns=columns,
            rows=rows,
            input_row_count=version.row_count,
            output_row_count=output_count,
            output_schema=output_schema,
        )

    async def submit(self, version_id: UUID, operation: Operation) -> TransformSubmission:
        version, schema, _ = self._version_context(version_id)
        PipelineCompiler(schema).validate(PipelineSpec(operations=(operation,)))
        key = _idempotency_key(version_id, operation)
        job = self.control_plane.create_job(
            kind="transform",
            idempotency_key=key,
            dataset_id=version.dataset_id,
            input_version_id=version.id,
            operation_payload={"operation": operation.model_dump(mode="json")},
        )
        if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
            await self.job_queue.publish_transform(
                job.id,
                idempotency_key=job.idempotency_key,
            )
            job = self.control_plane.get_job(job.id)
        return TransformSubmission(job=job, input_version_id=version.id)

    def parse_operation(self, payload: dict[str, Any]) -> Operation:
        return _OPERATION_ADAPTER.validate_python(payload)

    def history(self, version_id: UUID) -> tuple[TransformHistoryItem, ...]:
        current = self.control_plane.get_version(version_id)
        items: list[TransformHistoryItem] = []
        while current.parent_version_id is not None:
            job = self.control_plane.get_job_by_output_version_id(current.id)
            if job is not None and job.kind == "transform" and job.input_version_id is not None:
                operation = job.operation_payload.get("operation")
                if isinstance(operation, dict):
                    items.append(
                        TransformHistoryItem(
                            job_id=job.id,
                            input_version_id=job.input_version_id,
                            output_version_id=current.id,
                            output_version_number=current.version_number,
                            operation=operation,
                            created_at=job.created_at.isoformat(),
                        )
                    )
            current = self.control_plane.get_version(current.parent_version_id)
        items.reverse()
        return tuple(items)

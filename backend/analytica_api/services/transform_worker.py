from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import duckdb

from analytica_api.domain.control_plane import JobStatus
from analytica_api.domain.datasets import DatasetSchema, DatasetSource
from analytica_api.execution.duckdb_engine import PipelineCompiler
from analytica_api.operations.models import PipelineSpec
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.services.transform import DatasetTransformService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef


class TransformWorkerError(RuntimeError):
    pass


def _artifact_ref(artifact: object) -> StorageObjectRef:
    return StorageObjectRef(
        key=artifact.storage_key,  # type: ignore[attr-defined]
        byte_size=artifact.byte_size,  # type: ignore[attr-defined]
        content_type=artifact.content_type,  # type: ignore[attr-defined]
        checksum_sha256=artifact.checksum_sha256,  # type: ignore[attr-defined]
    )


def _quoted_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class TransformWorker:
    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        store: ArtifactStore,
        transform_service: DatasetTransformService,
    ):
        self.control_plane = control_plane
        self.store = store
        self.transform_service = transform_service

    def _mark_failed(self, job_id: UUID, exc: Exception) -> None:
        try:
            current = self.control_plane.get_job(job_id)
            if current.status == JobStatus.RUNNING:
                self.control_plane.transition_job(
                    job_id,
                    JobStatus.FAILED,
                    error_detail={"type": type(exc).__name__, "message": str(exc)[:2000]},
                )
        except ControlPlaneError:
            pass

    def run(self, job_id: UUID) -> UUID:
        job = self.control_plane.get_job(job_id)
        if (
            job.kind != "transform"
            or job.dataset_id is None
            or job.input_version_id is None
        ):
            raise TransformWorkerError("job is not a dataset transformation job")
        if job.status == JobStatus.SUCCEEDED:
            if job.output_version_id is None:
                raise TransformWorkerError("succeeded transform job has no output version")
            return job.output_version_id
        if job.status == JobStatus.CANCELLED:
            raise TransformWorkerError("cancelled transform jobs cannot run")

        try:
            if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
                job = self.control_plane.transition_job(job.id, JobStatus.RUNNING)
            elif job.status != JobStatus.RUNNING:
                raise TransformWorkerError(f"unsupported transform status: {job.status.value}")

            operation_payload = job.operation_payload.get("operation")
            if not isinstance(operation_payload, dict):
                raise TransformWorkerError("transform job has no operation payload")
            operation = self.transform_service.parse_operation(operation_payload)
            input_version = self.control_plane.get_version(job.input_version_id)
            if input_version.dataset_id != job.dataset_id:
                raise TransformWorkerError("input version belongs to another dataset")
            schema = DatasetSchema.model_validate(input_version.schema_snapshot)
            pipeline = PipelineSpec(operations=(operation,))
            compiler = PipelineCompiler(schema)
            output_schema = compiler.evolve_schema(pipeline)
            input_artifact = self.control_plane.get_artifact_for_version_kind(
                input_version.id, "canonical_dataset"
            )

            with TemporaryDirectory(prefix="analytica-transform-") as temp_dir:
                work_dir = Path(temp_dir)
                input_path = self.store.materialize(
                    _artifact_ref(input_artifact), work_dir / "input.parquet"
                )
                output_path = work_dir / "output.parquet"
                compiled = compiler.compile(DatasetSource(uri=str(input_path)), pipeline)
                connection = duckdb.connect(database=":memory:")
                try:
                    copy_sql = (
                        f"COPY ({compiled.sql}) TO {_quoted_literal(str(output_path))} "
                        "(FORMAT PARQUET, COMPRESSION ZSTD)"
                    )
                    connection.execute(copy_sql, compiled.parameters)
                    row = connection.execute(
                        "SELECT COUNT(*) FROM read_parquet(?)", [str(output_path)]
                    ).fetchone()
                finally:
                    connection.close()
                row_count = int(row[0]) if row is not None else 0

                canonical_key = f"datasets/{job.dataset_id}/transforms/{job.id}/data.parquet"
                try:
                    output_ref = self.store.put_file(
                        output_path,
                        key=canonical_key,
                        content_type="application/vnd.apache.parquet",
                    )
                except StorageError as upload_error:
                    try:
                        output_ref = self.store.stat(canonical_key)
                    except StorageError as stat_error:
                        raise upload_error from stat_error

                registered = self.control_plane.register_derived_version(
                    dataset_id=job.dataset_id,
                    parent_version_id=input_version.id,
                    schema=output_schema,
                    row_count=row_count,
                    object_ref=output_ref,
                    job_id=job.id,
                )
                output_version_id = registered.version.id

            latest = self.control_plane.get_job(job.id)
            if latest.status == JobStatus.SUCCEEDED:
                if latest.output_version_id is None:
                    raise TransformWorkerError("succeeded transform job has no output version")
                return latest.output_version_id
            if latest.status == JobStatus.FAILED:
                latest = self.control_plane.transition_job(latest.id, JobStatus.RUNNING)
            completed = self.control_plane.transition_job(
                latest.id,
                JobStatus.SUCCEEDED,
                output_version_id=output_version_id,
            )
            if completed.output_version_id is None:
                raise TransformWorkerError("completed transform job has no output version")
            return completed.output_version_id
        except Exception as exc:
            self._mark_failed(job.id, exc)
            raise

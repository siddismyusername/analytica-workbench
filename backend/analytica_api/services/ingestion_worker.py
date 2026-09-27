from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from analytica_api.config import Settings
from analytica_api.domain.control_plane import JobStatus
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.ingestion.models import SourceFormat
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef


class IngestionWorkerError(RuntimeError):
    pass


def _artifact_ref(
    *,
    key: str,
    byte_size: int,
    content_type: str,
    checksum_sha256: str | None,
) -> StorageObjectRef:
    return StorageObjectRef(
        key=key,
        byte_size=byte_size,
        content_type=content_type,
        checksum_sha256=checksum_sha256,
    )


class IngestionWorker:
    """Canonicalize one durable raw upload into exactly one dataset version."""

    def __init__(
        self,
        *,
        settings: Settings,
        control_plane: ControlPlaneService,
        store: ArtifactStore,
    ):
        self.control_plane = control_plane
        self.store = store
        self.engine = IngestionEngine(settings)

    def _mark_failed(self, job_id: UUID, exc: Exception) -> None:
        try:
            current = self.control_plane.get_job(job_id)
            if current.status == JobStatus.RUNNING:
                self.control_plane.transition_job(
                    job_id,
                    JobStatus.FAILED,
                    error_detail={
                        "type": type(exc).__name__,
                        "message": str(exc)[:2000],
                    },
                )
        except ControlPlaneError:
            pass

    def run(self, job_id: UUID) -> UUID:
        job = self.control_plane.get_job(job_id)
        if job.kind != "ingest" or job.dataset_id is None:
            raise IngestionWorkerError("job is not a dataset-ingestion job")
        if job.status == JobStatus.SUCCEEDED:
            if job.output_version_id is None:
                raise IngestionWorkerError("succeeded ingestion job has no output version")
            return job.output_version_id
        if job.status == JobStatus.CANCELLED:
            raise IngestionWorkerError("cancelled ingestion jobs cannot run")

        try:
            if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
                job = self.control_plane.transition_job(job.id, JobStatus.RUNNING)
            elif job.status != JobStatus.RUNNING:
                raise IngestionWorkerError(f"unsupported ingestion status: {job.status.value}")

            source_format = job.operation_payload.get("source_format")
            if source_format not in {"csv", "parquet"}:
                raise IngestionWorkerError("ingestion job has an unsupported source format")
            typed_source_format: SourceFormat = source_format

            raw_artifact = self.control_plane.get_artifact_for_job_kind(job.id, "raw_upload")
            raw_ref = _artifact_ref(
                key=raw_artifact.storage_key,
                byte_size=raw_artifact.byte_size,
                content_type=raw_artifact.content_type,
                checksum_sha256=raw_artifact.checksum_sha256,
            )

            with TemporaryDirectory(prefix="analytica-ingest-") as temp_dir:
                work_dir = Path(temp_dir)
                source_path = work_dir / f"source.{typed_source_format}"
                canonical_path = work_dir / "data.parquet"
                self.store.materialize(raw_ref, source_path)
                manifest = self.engine.ingest_local(
                    source_path,
                    canonical_path,
                    source_format=typed_source_format,
                )

                canonical_key = f"datasets/{job.dataset_id}/ingestions/{job.id}/data.parquet"
                try:
                    canonical_ref = self.store.put_file(
                        canonical_path,
                        key=canonical_key,
                        content_type="application/vnd.apache.parquet",
                    )
                except StorageError as upload_error:
                    try:
                        canonical_ref = self.store.stat(canonical_key)
                    except StorageError:
                        raise upload_error

                try:
                    registered = self.control_plane.register_ingested_version(
                        dataset_id=job.dataset_id,
                        manifest=manifest,
                        object_ref=canonical_ref,
                        job_id=job.id,
                    )
                    output_version_id = registered.version.id
                except IntegrityError:
                    canonical_artifact = self.control_plane.get_artifact_for_job_kind(
                        job.id, "canonical_dataset"
                    )
                    if canonical_artifact.dataset_version_id is None:
                        raise IngestionWorkerError(
                            "canonical artifact is missing its dataset version"
                        )
                    output_version_id = canonical_artifact.dataset_version_id

            latest = self.control_plane.get_job(job.id)
            if latest.status == JobStatus.SUCCEEDED:
                if latest.output_version_id is None:
                    raise IngestionWorkerError("succeeded ingestion job has no output version")
                return latest.output_version_id
            if latest.status == JobStatus.FAILED:
                latest = self.control_plane.transition_job(latest.id, JobStatus.RUNNING)
            if latest.status != JobStatus.RUNNING:
                raise IngestionWorkerError(
                    f"ingestion job cannot complete from status {latest.status.value}"
                )
            completed = self.control_plane.transition_job(
                latest.id,
                JobStatus.SUCCEEDED,
                output_version_id=output_version_id,
            )
            if completed.output_version_id is None:
                raise IngestionWorkerError("completed ingestion job has no output version")
            return completed.output_version_id
        except Exception as exc:
            self._mark_failed(job.id, exc)
            raise

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from analytica_api.domain.control_plane import JobStatus
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.ingestion.models import SourceFormat
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


class DatasetIngestionService:
    """Execute persisted ingestion jobs; safe to invoke after queue redelivery."""

    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
        ingestion_engine: IngestionEngine,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store
        self.ingestion_engine = ingestion_engine

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

    def run_job(self, job_id: UUID) -> UUID:
        job = self.control_plane.get_job(job_id)
        if job.kind != "ingest_dataset" or job.dataset_id is None:
            raise RuntimeError("job is not a dataset-ingestion job")
        if job.status == JobStatus.SUCCEEDED:
            if job.output_version_id is None:
                raise RuntimeError("succeeded ingestion job has no output version")
            return job.output_version_id
        if job.status == JobStatus.CANCELLED:
            raise RuntimeError("cancelled ingestion jobs cannot run")

        try:
            if job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
                try:
                    job = self.control_plane.transition_job(job.id, JobStatus.RUNNING)
                except ControlPlaneError:
                    job = self.control_plane.get_job(job.id)
                    if job.status != JobStatus.RUNNING:
                        raise

            source_format = job.operation_payload.get("source_format")
            if source_format not in {"csv", "parquet"}:
                raise RuntimeError("ingestion job has an unsupported source format")
            typed_source_format: SourceFormat = source_format

            source_artifact = self.control_plane.get_job_artifact(
                job.id, kind="source_dataset"
            )
            if source_artifact is None:
                raise RuntimeError("ingestion job has no source artifact")
            source_ref = StorageObjectRef(
                key=source_artifact.storage_key,
                byte_size=source_artifact.byte_size,
                content_type=source_artifact.content_type,
                checksum_sha256=source_artifact.checksum_sha256,
            )

            with TemporaryDirectory(prefix="analytica-ingest-") as directory:
                workdir = Path(directory)
                suffix = ".csv" if typed_source_format == "csv" else ".parquet"
                source_path = self.artifact_store.materialize(
                    source_ref, workdir / f"source{suffix}"
                )
                canonical_path = workdir / "canonical.parquet"
                manifest = self.ingestion_engine.ingest_local(
                    source_path,
                    canonical_path,
                    source_format=typed_source_format,
                )

                canonical_key = (
                    f"datasets/{job.dataset_id}/ingestions/{job.id}/canonical.parquet"
                )
                try:
                    canonical_ref = self.artifact_store.put_file(
                        canonical_path,
                        key=canonical_key,
                        content_type=PARQUET_CONTENT_TYPE,
                    )
                except StorageError as upload_error:
                    try:
                        canonical_ref = self.artifact_store.stat(canonical_key)
                    except StorageError:
                        raise upload_error

                try:
                    registered = self.control_plane.register_ingested_version(
                        dataset_id=job.dataset_id,
                        manifest=manifest,
                        object_ref=canonical_ref,
                        job_id=job.id,
                    )
                    version_id = registered.version.id
                except IntegrityError:
                    existing = self.control_plane.get_job_artifact(
                        job.id, kind="canonical_dataset"
                    )
                    if existing is None or existing.dataset_version_id is None:
                        raise
                    version_id = existing.dataset_version_id

            latest = self.control_plane.get_job(job.id)
            if latest.status == JobStatus.SUCCEEDED:
                if latest.output_version_id is None:
                    raise RuntimeError("succeeded ingestion job has no output version")
                return latest.output_version_id
            if latest.status == JobStatus.FAILED:
                latest = self.control_plane.transition_job(latest.id, JobStatus.RUNNING)
            if latest.status != JobStatus.RUNNING:
                raise RuntimeError(
                    f"ingestion job cannot complete from status {latest.status.value}"
                )
            completed = self.control_plane.transition_job(
                latest.id,
                JobStatus.SUCCEEDED,
                output_version_id=version_id,
            )
            if completed.output_version_id is None:
                raise RuntimeError("completed ingestion job has no output version")
            return completed.output_version_id
        except Exception as exc:
            self._mark_failed(job.id, exc)
            raise

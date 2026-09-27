from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from analytica_api.domain.control_plane import JobRecord, JobStatus
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.ingestion.models import SourceFormat
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


@dataclass(frozen=True)
class IngestionResult:
    job: JobRecord
    dataset_id: UUID
    version_id: UUID


class DatasetIngestionService:
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

    def ingest_uploaded_dataset(
        self,
        *,
        name: str,
        source_ref: StorageObjectRef,
        source_format: SourceFormat,
        idempotency_key: str,
    ) -> IngestionResult:
        existing = self.control_plane.get_job_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.output_version_id is None or existing.dataset_id is None:
                raise RuntimeError(
                    f"idempotent ingestion job {existing.id} has not completed successfully"
                )
            return IngestionResult(
                job=existing,
                dataset_id=existing.dataset_id,
                version_id=existing.output_version_id,
            )

        dataset = self.control_plane.create_dataset(name)
        job = self.control_plane.create_job(
            kind="ingest_dataset",
            idempotency_key=idempotency_key,
            dataset_id=dataset.id,
            operation_payload={
                "source_key": source_ref.key,
                "source_format": source_format,
                "source_byte_size": source_ref.byte_size,
            },
        )
        self.control_plane.register_job_artifact(
            job_id=job.id,
            kind="source_dataset",
            object_ref=source_ref,
        )
        self.control_plane.transition_job(job.id, JobStatus.RUNNING)

        try:
            with TemporaryDirectory(prefix="analytica-ingest-") as directory:
                workdir = Path(directory)
                suffix = ".csv" if source_format == "csv" else ".parquet"
                source_path = self.artifact_store.materialize(
                    source_ref, workdir / f"source{suffix}"
                )
                canonical_path = workdir / "canonical.parquet"
                manifest = self.ingestion_engine.ingest_local(
                    source_path,
                    canonical_path,
                    source_format=source_format,
                )
                canonical_ref = self.artifact_store.put_file(
                    canonical_path,
                    key=f"datasets/{dataset.id}/ingestions/{job.id}/canonical.parquet",
                    content_type=PARQUET_CONTENT_TYPE,
                )
                registered = self.control_plane.register_ingested_version(
                    dataset_id=dataset.id,
                    manifest=manifest,
                    object_ref=canonical_ref,
                )

            completed = self.control_plane.transition_job(
                job.id,
                JobStatus.SUCCEEDED,
                output_version_id=registered.version.id,
            )
            return IngestionResult(
                job=completed,
                dataset_id=dataset.id,
                version_id=registered.version.id,
            )
        except Exception as exc:
            self.control_plane.transition_job(
                job.id,
                JobStatus.FAILED,
                error_detail={"type": type(exc).__name__, "message": str(exc)},
            )
            raise

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from analytica_api.config import Settings
from analytica_api.domain.control_plane import JobRecord, JobStatus
from analytica_api.ingestion.models import SourceFormat
from analytica_api.queue.contracts import JobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore


@dataclass(frozen=True)
class IngestionSubmission:
    job: JobRecord
    dataset_id: UUID


def _source_format(source_key: str) -> SourceFormat:
    path = PurePosixPath(source_key)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 3 or path.parts[0] != "raw":
        raise ValueError("source_key must identify an object under raw/<upload-id>/<filename>")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".parquet":
        return "parquet"
    raise ValueError("only CSV and Parquet source objects are supported")


def _idempotency_key(source_key: str) -> str:
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return f"ingest:{digest}"


class DatasetIngestionService:
    """Verify a direct upload, persist one durable ingestion job, and dispatch it."""

    def __init__(
        self,
        *,
        settings: Settings,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
        job_queue: JobQueue,
    ):
        self.settings = settings
        self.control_plane = control_plane
        self.artifact_store = artifact_store
        self.job_queue = job_queue

    async def submit_uploaded_dataset(
        self,
        *,
        name: str,
        source_key: str,
    ) -> IngestionSubmission:
        source_format = _source_format(source_key)
        source_ref = await asyncio.to_thread(self.artifact_store.stat, source_key)

        if (
            self.settings.max_upload_bytes is not None
            and source_ref.byte_size > self.settings.max_upload_bytes
        ):
            limit = self.settings.max_upload_bytes
            raise ValueError(f"uploaded object exceeds configured limit of {limit} bytes")

        idempotency_key = _idempotency_key(source_ref.key)
        created = await asyncio.to_thread(
            self.control_plane.create_ingestion_job,
            dataset_name=name,
            source_format=source_format,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
        )

        if created.job.status in {JobStatus.QUEUED, JobStatus.FAILED}:
            dispatch_key = f"{idempotency_key}:attempt:{created.job.attempt_count + 1}"
            await self.job_queue.publish_ingestion(
                created.job.id,
                idempotency_key=dispatch_key,
            )

        latest = await asyncio.to_thread(self.control_plane.get_job, created.job.id)
        return IngestionSubmission(job=latest, dataset_id=created.dataset.id)

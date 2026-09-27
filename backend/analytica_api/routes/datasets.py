import hashlib
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.config import Settings, get_settings
from analytica_api.domain.control_plane import DatasetVersionState, JobStatus
from analytica_api.domain.datasets import DatasetSchema, DatasetSource
from analytica_api.execution.duckdb_engine import DuckDBEngine
from analytica_api.ingestion.models import SourceFormat
from analytica_api.operations.models import PipelineSpec
from analytica_api.queue.contracts import JobQueue
from analytica_api.runtime import get_artifact_store, get_control_plane, get_job_queue
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageError, StorageObjectRef

router = APIRouter(prefix="/datasets", tags=["datasets"])


class UploadCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str = Field(min_length=1, max_length=255)
    storage_key: str = Field(min_length=1, max_length=1024)


class UploadCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: UUID
    job_id: UUID
    job_status: JobStatus
    output_version_id: UUID | None


def _source_format(storage_key: str) -> SourceFormat:
    path = PurePosixPath(storage_key)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "raw":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="storage_key must reference a raw upload",
        )
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".parquet":
        return "parquet"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="only CSV and Parquet uploads are currently supported",
    )


def _object_ref_from_artifact(artifact) -> StorageObjectRef:
    return StorageObjectRef(
        key=artifact.storage_key,
        byte_size=artifact.byte_size,
        content_type=artifact.content_type,
        checksum_sha256=artifact.checksum_sha256,
    )


@router.post(
    "/uploads/complete",
    response_model=UploadCompletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_upload(
    request: UploadCompletionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    control_plane: Annotated[ControlPlaneService, Depends(get_control_plane)],
    store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> UploadCompletionResponse:
    source_format = _source_format(request.storage_key)
    try:
        source_ref = store.stat(request.storage_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded object is unavailable",
        ) from exc

    if settings.max_upload_bytes is not None and source_ref.byte_size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="uploaded object exceeds the configured product limit",
        )

    idempotency_key = "ingest:" + hashlib.sha256(
        request.storage_key.encode("utf-8")
    ).hexdigest()
    try:
        created = control_plane.create_ingestion_job(
            dataset_name=request.dataset_name,
            source_format=source_format,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
        )
        await queue.publish_ingestion(
            created.job.id,
            idempotency_key=idempotency_key,
        )
        current_job = control_plane.get_job(created.job.id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingestion job could not be published; retrying this request is safe",
        ) from exc

    return UploadCompletionResponse(
        dataset_id=created.dataset.id,
        job_id=current_job.id,
        job_status=current_job.status,
        output_version_id=current_job.output_version_id,
    )


@router.get("/{dataset_id}/versions/{version_id}/preview")
def preview_dataset_version(
    dataset_id: UUID,
    version_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    control_plane: Annotated[ControlPlaneService, Depends(get_control_plane)],
    store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    limit: Annotated[int, Query(ge=1, le=5000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    if limit > settings.preview_max_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"preview limit cannot exceed {settings.preview_max_rows} rows",
        )

    try:
        version = control_plane.get_version(version_id)
        if version.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="dataset version not found",
            )
        if version.state != DatasetVersionState.READY:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="dataset version is not ready",
            )
        artifact = control_plane.get_artifact_for_version_kind(
            version.id, "canonical_dataset"
        )
    except ControlPlaneError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    object_ref = _object_ref_from_artifact(artifact)
    schema = DatasetSchema.model_validate(version.schema_snapshot)

    with TemporaryDirectory(prefix="analytica-preview-") as temp_dir:
        local_path = store.materialize(
            object_ref,
            PurePosixPath(temp_dir) / "data.parquet",  # type: ignore[arg-type]
        )
        table = DuckDBEngine(settings).preview(
            DatasetSource(uri=str(local_path)),
            schema,
            PipelineSpec(),
            limit=limit,
            offset=offset,
        )

    return {
        "dataset_id": str(dataset_id),
        "version_id": str(version.id),
        "version_number": version.version_number,
        "total_rows": version.row_count,
        "offset": offset,
        "returned_rows": table.num_rows,
        "columns": [column.model_dump(mode="json") for column in schema.columns],
        "rows": table.to_pylist(),
    }

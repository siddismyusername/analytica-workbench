import hashlib
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.config import Settings, get_settings
from analytica_api.domain.control_plane import JobRecord
from analytica_api.ingestion.models import SourceFormat
from analytica_api.queue.contracts import JobQueue
from analytica_api.runtime import (
    get_artifact_store,
    get_control_plane,
    get_job_queue,
    get_preview_service,
)
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.contracts import ArtifactStore, StorageError

router = APIRouter(tags=["datasets"])


class UploadedDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    source_key: str = Field(min_length=1, max_length=1024)


class IngestionResponse(BaseModel):
    job_id: UUID
    dataset_id: UUID
    version_id: UUID | None
    status: str


class PreviewResponse(BaseModel):
    version_id: UUID
    columns: list[str]
    rows: list[list[object]]
    offset: int
    limit: int


def _source_format(source_key: str) -> SourceFormat:
    path = PurePosixPath(source_key)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 3
        or path.parts[:2] != ("datasets", "source")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_key must reference an uploaded dataset source",
        )
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".parquet":
        return "parquet"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="only CSV and Parquet datasets are currently supported",
    )


@router.post(
    "/datasets/ingestions",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_uploaded_dataset(
    payload: UploadedDatasetRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    control_plane: Annotated[ControlPlaneService, Depends(get_control_plane)],
    artifact_store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> IngestionResponse:
    source_format = _source_format(payload.source_key)
    try:
        source_ref = artifact_store.stat(payload.source_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded dataset source is unavailable",
        ) from exc

    if settings.max_upload_bytes is not None and source_ref.byte_size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail="uploaded dataset exceeds the configured product limit",
        )

    idempotency_key = "ingest:" + hashlib.sha256(
        payload.source_key.encode("utf-8")
    ).hexdigest()
    try:
        created = control_plane.create_ingestion_job(
            dataset_name=payload.name,
            source_format=source_format,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
        )
        await job_queue.publish_ingestion(
            created.job.id,
            idempotency_key=idempotency_key,
        )
        current = control_plane.get_job(created.job.id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingestion could not be published; retrying this request is safe",
        ) from exc

    return IngestionResponse(
        job_id=current.id,
        dataset_id=created.dataset.id,
        version_id=current.output_version_id,
        status=current.status.value,
    )


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(
    job_id: UUID,
    control_plane: Annotated[ControlPlaneService, Depends(get_control_plane)],
) -> JobRecord:
    try:
        return control_plane.get_job(job_id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/datasets/versions/{version_id}/preview", response_model=PreviewResponse)
def preview_dataset(
    version_id: UUID,
    preview: Annotated[DatasetPreviewService, Depends(get_preview_service)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PreviewResponse:
    try:
        result = preview.preview(version_id, offset=offset, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PreviewResponse(
        version_id=result.version_id,
        columns=list(result.columns),
        rows=[list(row) for row in result.rows],
        offset=result.offset,
        limit=result.limit,
    )

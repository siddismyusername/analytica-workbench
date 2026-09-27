from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.runtime import get_control_plane, get_ingestion_service, get_preview_service
from analytica_api.services.control_plane import ControlPlaneError
from analytica_api.storage.contracts import StorageError

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


def _ingestion_response(job_id: UUID) -> IngestionResponse:
    job = get_control_plane().get_job(job_id)
    if job.dataset_id is None:
        raise ControlPlaneError("ingestion job has no dataset")
    return IngestionResponse(
        job_id=job.id,
        dataset_id=job.dataset_id,
        version_id=job.output_version_id,
        status=job.status.value,
    )


@router.post(
    "/datasets/ingestions",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_uploaded_dataset(payload: UploadedDatasetRequest) -> IngestionResponse:
    try:
        submission = await get_ingestion_service().submit_uploaded_dataset(
            name=payload.name,
            source_key=payload.source_key,
        )
        return _ingestion_response(submission.job.id)
    except (ControlPlaneError, StorageError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/datasets/ingestions/{job_id}", response_model=IngestionResponse)
def ingestion_status(job_id: UUID) -> IngestionResponse:
    try:
        return _ingestion_response(job_id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/datasets/versions/{version_id}/preview", response_model=PreviewResponse)
def preview_dataset(
    version_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PreviewResponse:
    try:
        result = get_preview_service().preview(version_id, offset=offset, limit=limit)
    except (LookupError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PreviewResponse(
        version_id=result.version_id,
        columns=list(result.columns),
        rows=[list(row) for row in result.rows],
        offset=result.offset,
        limit=result.limit,
    )

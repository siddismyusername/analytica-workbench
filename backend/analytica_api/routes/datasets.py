from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.runtime import (
    get_control_plane,
    get_ingestion_service,
    get_preview_service,
    get_profile_service,
)
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


class ColumnProfileResponse(BaseModel):
    name: str
    display_name: str
    data_type: str
    storage_type: str | None
    nullable: bool
    null_count: int
    null_percentage: float
    distinct_count: int


class ProfileWarningResponse(BaseModel):
    code: str
    severity: str
    message: str


class ProfileResponse(BaseModel):
    version_id: UUID
    dataset_id: UUID
    dataset_name: str
    version_number: int
    row_count: int
    column_count: int
    byte_size: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    duplicate_percentage: float
    columns: list[ColumnProfileResponse]
    warnings: list[ProfileWarningResponse]


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


@router.get("/datasets/versions/{version_id}/profile", response_model=ProfileResponse)
def profile_dataset(version_id: UUID) -> ProfileResponse:
    try:
        result = get_profile_service().profile(version_id)
    except (LookupError, ControlPlaneError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ProfileResponse(
        version_id=result.version_id,
        dataset_id=result.dataset_id,
        dataset_name=result.dataset_name,
        version_number=result.version_number,
        row_count=result.row_count,
        column_count=result.column_count,
        byte_size=result.byte_size,
        missing_cells=result.missing_cells,
        missing_percentage=result.missing_percentage,
        duplicate_rows=result.duplicate_rows,
        duplicate_percentage=result.duplicate_percentage,
        columns=[
            ColumnProfileResponse(
                name=column.name,
                display_name=column.display_name,
                data_type=column.data_type,
                storage_type=column.storage_type,
                nullable=column.nullable,
                null_count=column.null_count,
                null_percentage=column.null_percentage,
                distinct_count=column.distinct_count,
            )
            for column in result.columns
        ],
        warnings=[
            ProfileWarningResponse(
                code=warning.code,
                severity=warning.severity,
                message=warning.message,
            )
            for warning in result.warnings
        ],
    )

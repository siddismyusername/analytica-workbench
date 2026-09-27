from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.config import get_settings
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.persistence.database import Database
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef
from analytica_api.storage.local import LocalArtifactStore
from analytica_api.storage.vercel_blob import VercelBlobArtifactStore

router = APIRouter(tags=["datasets"])


class UploadedDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    source_key: str = Field(min_length=1)
    source_format: Literal["csv", "parquet"]
    source_byte_size: int = Field(ge=0)
    source_content_type: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=255)


class IngestionResponse(BaseModel):
    job_id: UUID
    dataset_id: UUID
    version_id: UUID
    status: str


class PreviewResponse(BaseModel):
    version_id: UUID
    columns: list[str]
    rows: list[list[object]]
    offset: int
    limit: int


@lru_cache(maxsize=1)
def _services() -> tuple[ControlPlaneService, DatasetIngestionService, DatasetPreviewService]:
    settings = get_settings()
    database = Database(settings.database_url)
    control_plane = ControlPlaneService(
        lambda: SqlAlchemyUnitOfWork(database.session_factory)
    )
    store: ArtifactStore
    if settings.artifact_store_backend == "vercel_blob":
        store = VercelBlobArtifactStore()
    else:
        store = LocalArtifactStore(Path(settings.local_artifact_root))

    ingestion = DatasetIngestionService(
        control_plane=control_plane,
        artifact_store=store,
        ingestion_engine=IngestionEngine(settings),
    )
    preview = DatasetPreviewService(
        control_plane=control_plane,
        artifact_store=store,
    )
    return control_plane, ingestion, preview


@router.post("/datasets/ingestions", response_model=IngestionResponse)
def ingest_uploaded_dataset(payload: UploadedDatasetRequest) -> IngestionResponse:
    _, ingestion, _ = _services()
    source_ref = StorageObjectRef(
        key=payload.source_key,
        byte_size=payload.source_byte_size,
        content_type=payload.source_content_type,
    )
    try:
        result = ingestion.ingest_uploaded_dataset(
            name=payload.name,
            source_ref=source_ref,
            source_format=payload.source_format,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestionResponse(
        job_id=result.job.id,
        dataset_id=result.dataset_id,
        version_id=result.version_id,
        status=result.job.status.value,
    )


@router.get("/datasets/versions/{version_id}/preview", response_model=PreviewResponse)
def preview_dataset(
    version_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PreviewResponse:
    _, _, preview = _services()
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

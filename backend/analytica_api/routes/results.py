"""Saved results and durable report, chart, and dataset exports."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from analytica_api.domain.control_plane import ArtifactRecord, JobRecord, SavedResultRecord
from analytica_api.runtime import get_artifact_store, get_control_plane, get_results_service
from analytica_api.services.control_plane import ControlPlaneError
from analytica_api.services.results import ResultsValidationError
from analytica_api.storage.contracts import StorageError, StorageObjectRef

router = APIRouter(tags=["results"])


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dataset_csv", "dataset_parquet", "report_html", "chart_svg"]
    title: str = Field(default="", max_length=160)
    result_ids: list[UUID] = Field(default_factory=list, max_length=30)


class ExportResponse(BaseModel):
    job_id: UUID | None
    version_id: UUID
    status: str
    kind: str
    artifact_id: UUID | None
    error_detail: dict[str, Any] | None
    title: str | None
    created_at: datetime


def _export_response(value: JobRecord | ArtifactRecord) -> ExportResponse:
    if isinstance(value, ArtifactRecord):
        if value.dataset_version_id is None:
            raise HTTPException(404, "dataset artifact not found")
        return ExportResponse(
            job_id=None,
            version_id=value.dataset_version_id,
            status="succeeded",
            kind="dataset_parquet",
            artifact_id=value.id,
            error_detail=None,
            title=None,
            created_at=value.created_at,
        )
    if value.kind != "results_export" or value.input_version_id is None:
        raise HTTPException(404, "export job not found")
    kind = value.operation_payload["kind"]
    artifact_id = None
    if value.status.value == "succeeded":
        artifact_id = get_control_plane().get_artifact_for_job_kind(value.id, kind).id
    return ExportResponse(
        job_id=value.id,
        version_id=value.input_version_id,
        status=value.status.value,
        kind=kind,
        artifact_id=artifact_id,
        error_detail=value.error_detail,
        title=value.operation_payload.get("title") or None,
        created_at=value.created_at,
    )


@router.get("/datasets/versions/{version_id}/results", response_model=list[SavedResultRecord])
def list_results(version_id: UUID) -> list[SavedResultRecord]:
    try:
        return list(get_results_service().list_results(version_id))
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/results/{result_id}", response_model=SavedResultRecord)
def get_result(result_id: UUID) -> SavedResultRecord:
    try:
        return get_control_plane().get_result(result_id)
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post(
    "/datasets/versions/{version_id}/exports", response_model=ExportResponse, status_code=202
)
async def create_export(version_id: UUID, request: ExportRequest) -> ExportResponse:
    try:
        value = await get_results_service().submit(
            version_id,
            kind=request.kind,
            title=request.title,
            result_ids=request.result_ids,
        )
        return _export_response(value)
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ResultsValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/exports/{job_id}", response_model=ExportResponse)
def get_export(job_id: UUID) -> ExportResponse:
    try:
        return _export_response(get_control_plane().get_job(job_id))
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/datasets/versions/{version_id}/exports", response_model=list[ExportResponse])
def list_exports(version_id: UUID) -> list[ExportResponse]:
    try:
        jobs = get_control_plane().list_jobs_for_version(version_id, "results_export")
        return [_export_response(job) for job in jobs]
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: UUID) -> FileResponse:
    try:
        artifact = get_control_plane().get_artifact(artifact_id)
    except ControlPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc
    filenames = {
        "canonical_dataset": "dataset.parquet",
        "dataset_csv": "dataset.csv",
        "report_html": "report.html",
        "chart_svg": "chart.svg",
    }
    if artifact.kind not in filenames:
        raise HTTPException(404, "artifact is not available for download")
    if artifact.job_id is not None and artifact.kind != "canonical_dataset":
        job = get_control_plane().get_job(artifact.job_id)
        if job.kind != "results_export" or job.status.value != "succeeded":
            raise HTTPException(404, "export is not ready")
    temp = TemporaryDirectory(prefix="analytica-download-")
    path = Path(temp.name) / filenames[artifact.kind]
    try:
        get_artifact_store().materialize(
            StorageObjectRef(
                key=artifact.storage_key,
                byte_size=artifact.byte_size,
                content_type=artifact.content_type,
                checksum_sha256=artifact.checksum_sha256,
            ),
            path,
        )
    except StorageError as exc:
        temp.cleanup()
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(
        path,
        media_type=artifact.content_type,
        filename=filenames[artifact.kind],
        background=BackgroundTask(temp.cleanup),
        headers={"X-Content-Type-Options": "nosniff"},
    )

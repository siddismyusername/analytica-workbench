from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from analytica_api.domain.control_plane import JobRecord
from analytica_api.runtime import get_control_plane, get_model_service
from analytica_api.services.control_plane import ControlPlaneError
from analytica_api.services.modeling import ModelRunConfig, ModelValidationError

router = APIRouter(tags=["modeling"])


class ModelRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    version_id: UUID
    status: str
    configuration: ModelRunConfig
    error_detail: dict[str, Any] | None
    result: dict[str, Any] | None
    artifacts: dict[str, UUID]


def _response(job: JobRecord) -> ModelRunResponse:
    if job.kind != "model_train" or job.input_version_id is None:
        raise HTTPException(status_code=404, detail="model run not found")
    artifacts = {}
    if job.status.value == "succeeded":
        for kind in ("model_evaluation", "model_pipeline"):
            artifacts[kind] = get_control_plane().get_artifact_for_job_kind(job.id, kind).id
    return ModelRunResponse(
        job_id=job.id,
        version_id=job.input_version_id,
        status=job.status.value,
        configuration=ModelRunConfig.model_validate(job.operation_payload["configuration"]),
        error_detail=job.error_detail,
        result=get_model_service().result(job.id),
        artifacts=artifacts,
    )


@router.post(
    "/datasets/versions/{version_id}/models/runs", response_model=ModelRunResponse, status_code=202
)
async def submit_model_run(version_id: UUID, config: ModelRunConfig) -> ModelRunResponse:
    try:
        job = await get_model_service().submit(version_id, config)
        return _response(job)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/datasets/versions/{version_id}/models/runs", response_model=list[ModelRunResponse])
def list_model_runs(version_id: UUID) -> list[ModelRunResponse]:
    try:
        jobs = get_control_plane().list_jobs_for_version(version_id, "model_train")
        return [_response(job) for job in jobs]
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models/runs/{job_id}", response_model=ModelRunResponse)
def get_model_run(job_id: UUID) -> ModelRunResponse:
    try:
        return _response(get_control_plane().get_job(job_id))
    except ControlPlaneError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

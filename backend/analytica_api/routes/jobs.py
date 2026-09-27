from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from analytica_api.domain.control_plane import JobRecord
from analytica_api.runtime import get_control_plane
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobRecord)
def get_job(
    job_id: UUID,
    control_plane: Annotated[ControlPlaneService, Depends(get_control_plane)],
) -> JobRecord:
    try:
        return control_plane.get_job(job_id)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

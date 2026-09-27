from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.domain.datasets import DatasetSchema
from analytica_api.execution.duckdb_engine import PipelineCompilationError, PipelineCompiler
from analytica_api.operations.models import PipelineSpec
from analytica_api.operations.registry import OperationDescriptor, operation_catalog

router = APIRouter(prefix="/operations", tags=["operations"])


class ValidatePipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_schema: DatasetSchema = Field(alias="schema")
    pipeline: PipelineSpec


class ValidatePipelineResponse(BaseModel):
    valid: bool
    active_column_ids: tuple[str, ...]


@router.get("", response_model=tuple[OperationDescriptor, ...])
async def list_operations() -> tuple[OperationDescriptor, ...]:
    return operation_catalog()


@router.post("/validate", response_model=ValidatePipelineResponse)
async def validate_pipeline(request: ValidatePipelineRequest) -> ValidatePipelineResponse:
    try:
        active = PipelineCompiler(request.dataset_schema).validate(request.pipeline)
    except PipelineCompilationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ValidatePipelineResponse(valid=True, active_column_ids=active)

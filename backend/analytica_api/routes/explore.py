import hashlib
import json
from typing import Any
from uuid import UUID

import duckdb
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.runtime import get_control_plane, get_explore_service
from analytica_api.services.control_plane import ControlPlaneError
from analytica_api.services.explore import ExploreValidationError

router = APIRouter(tags=["explore"])


class DescriptiveResponse(BaseModel):
    version_id: UUID
    column_id: str
    column_name: str
    data_type: str
    row_count: int
    valid_count: int
    missing_count: int
    distinct_count: int
    minimum: Any | None
    maximum: Any | None
    mean: float | None
    stddev: float | None
    q1: float | None
    median: float | None
    q3: float | None
    mode: Any | None
    mode_count: int


class FrequencyItemResponse(BaseModel):
    value: Any | None
    count: int
    percentage: float


class FrequencyResponse(BaseModel):
    version_id: UUID
    column_id: str
    column_name: str
    total_rows: int
    truncated: bool
    items: list[FrequencyItemResponse]


class CorrelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_ids: list[str] | None = None


class CorrelationColumnResponse(BaseModel):
    column_id: str
    name: str


class CorrelationResponse(BaseModel):
    version_id: UUID
    method: str
    columns: list[CorrelationColumnResponse]
    matrix: list[list[float | None]]


class CrosstabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_column_id: str
    column_column_id: str
    limit: int = Field(default=12, ge=2, le=20)


class CrosstabResponse(BaseModel):
    version_id: UUID
    row_column: CorrelationColumnResponse
    column_column: CorrelationColumnResponse
    row_values: list[Any | None]
    column_values: list[Any | None]
    counts: list[list[int]]
    row_totals: list[int]
    column_totals: list[int]
    total: int
    row_truncated: bool
    column_truncated: bool


class VisualizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_type: str
    x_column_id: str
    y_column_id: str | None = None
    bins: int = Field(default=20, ge=5, le=100)
    limit: int = Field(default=1000, ge=5, le=5000)


class VisualizationResponse(BaseModel):
    version_id: UUID
    chart_type: str
    title: str
    x_label: str | None
    y_label: str | None
    data: list[dict[str, Any]]
    metadata: dict[str, Any]


def _handle_not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _handle_invalid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/datasets/versions/{version_id}/explore/descriptives/{column_id}",
    response_model=DescriptiveResponse,
)
def descriptives(version_id: UUID, column_id: str) -> DescriptiveResponse:
    try:
        result = get_explore_service().describe(version_id, column_id)
    except ControlPlaneError as exc:
        raise _handle_not_found(exc) from exc
    except (ExploreValidationError, duckdb.Error) as exc:
        raise _handle_invalid(exc) from exc
    return DescriptiveResponse(**result.__dict__)


@router.get(
    "/datasets/versions/{version_id}/explore/frequencies/{column_id}",
    response_model=FrequencyResponse,
)
def frequencies(
    version_id: UUID,
    column_id: str,
    limit: int = Query(default=30, ge=1, le=100),
) -> FrequencyResponse:
    try:
        result = get_explore_service().frequencies(version_id, column_id, limit=limit)
    except ControlPlaneError as exc:
        raise _handle_not_found(exc) from exc
    except (ExploreValidationError, duckdb.Error) as exc:
        raise _handle_invalid(exc) from exc
    return FrequencyResponse(
        version_id=result.version_id,
        column_id=result.column_id,
        column_name=result.column_name,
        total_rows=result.total_rows,
        truncated=result.truncated,
        items=[FrequencyItemResponse(**item.__dict__) for item in result.items],
    )


@router.post(
    "/datasets/versions/{version_id}/explore/correlations",
    response_model=CorrelationResponse,
)
def correlations(version_id: UUID, payload: CorrelationRequest) -> CorrelationResponse:
    try:
        result = get_explore_service().correlation(
            version_id,
            tuple(payload.column_ids) if payload.column_ids else None,
        )
    except ControlPlaneError as exc:
        raise _handle_not_found(exc) from exc
    except (ExploreValidationError, duckdb.Error) as exc:
        raise _handle_invalid(exc) from exc
    return CorrelationResponse(
        version_id=result.version_id,
        method=result.method,
        columns=[
            CorrelationColumnResponse(column_id=column_id, name=name)
            for column_id, name in result.columns
        ],
        matrix=[list(row) for row in result.matrix],
    )


@router.post(
    "/datasets/versions/{version_id}/explore/crosstab",
    response_model=CrosstabResponse,
)
def crosstab(version_id: UUID, payload: CrosstabRequest) -> CrosstabResponse:
    try:
        result = get_explore_service().crosstab(
            version_id,
            payload.row_column_id,
            payload.column_column_id,
            limit=payload.limit,
        )
    except ControlPlaneError as exc:
        raise _handle_not_found(exc) from exc
    except (ExploreValidationError, duckdb.Error) as exc:
        raise _handle_invalid(exc) from exc
    return CrosstabResponse(
        version_id=result.version_id,
        row_column=CorrelationColumnResponse(
            column_id=result.row_column[0], name=result.row_column[1]
        ),
        column_column=CorrelationColumnResponse(
            column_id=result.column_column[0], name=result.column_column[1]
        ),
        row_values=list(result.row_values),
        column_values=list(result.column_values),
        counts=[list(row) for row in result.counts],
        row_totals=list(result.row_totals),
        column_totals=list(result.column_totals),
        total=result.total,
        row_truncated=result.row_truncated,
        column_truncated=result.column_truncated,
    )


@router.post(
    "/datasets/versions/{version_id}/explore/visualizations",
    response_model=VisualizationResponse,
)
def visualization(version_id: UUID, payload: VisualizationRequest) -> VisualizationResponse:
    try:
        result = get_explore_service().visualization(
            version_id,
            payload.chart_type,
            payload.x_column_id,
            y_column_id=payload.y_column_id,
            bins=payload.bins,
            limit=payload.limit,
        )
    except ControlPlaneError as exc:
        raise _handle_not_found(exc) from exc
    except (ExploreValidationError, duckdb.Error) as exc:
        raise _handle_invalid(exc) from exc
    response = VisualizationResponse(
        version_id=result.version_id,
        chart_type=result.chart_type,
        title=result.title,
        x_label=result.x_label,
        y_label=result.y_label,
        data=list(result.data),
        metadata=result.metadata,
    )
    configuration = payload.model_dump(mode="json")
    fingerprint = hashlib.sha256(
        json.dumps(["visualization", str(version_id), configuration], sort_keys=True).encode()
    ).hexdigest()
    get_control_plane().save_result(
        version_id=version_id,
        kind="chart",
        title=result.title,
        fingerprint=fingerprint,
        configuration=configuration,
        payload=response.model_dump(mode="json"),
    )
    return response

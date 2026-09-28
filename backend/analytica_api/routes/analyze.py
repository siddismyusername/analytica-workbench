from typing import Any, Literal
from uuid import UUID

import duckdb
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from analytica_api.runtime import get_analyze_service
from analytica_api.services.analyze import AnalyzeValidationError
from analytica_api.services.control_plane import ControlPlaneError

router = APIRouter(tags=["analyze"])

AnalysisGoal = Literal[
    "compare_groups",
    "compare_paired",
    "numeric_relationship",
    "categorical_association",
    "one_sample",
]
TestId = Literal[
    "welch_t",
    "paired_t",
    "one_sample_t",
    "welch_anova",
    "mann_whitney",
    "wilcoxon",
    "kruskal",
    "chi_square",
    "pearson",
    "spearman",
]
Alternative = Literal["two-sided", "less", "greater"]


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: AnalysisGoal
    outcome_column_id: str | None = None
    group_column_id: str | None = None
    secondary_column_id: str | None = None


class RecommendationItemResponse(BaseModel):
    test_id: TestId
    name: str
    preferred: bool
    rationale: str
    assumptions: list[str]


class RecommendationResponse(BaseModel):
    version_id: UUID
    goal: AnalysisGoal
    recommendations: list[RecommendationItemResponse]
    notes: list[str]


class AnalysisRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_id: TestId
    x_column_id: str
    y_column_id: str | None = None
    group_column_id: str | None = None
    reference_value: float | None = None
    confidence_level: float = Field(default=0.95, ge=0.8, lt=1)
    alternative: Alternative = "two-sided"


class EstimateResponse(BaseModel):
    name: str
    value: float


class ConfidenceIntervalResponse(BaseModel):
    level: float
    low: float | None
    high: float | None
    label: str


class StatisticResponse(BaseModel):
    name: str
    value: float
    degrees_of_freedom: float | None


class EffectSizeResponse(BaseModel):
    name: str
    value: float
    magnitude: str | None


class DiagnosticResponse(BaseModel):
    name: str
    statistic: float | None
    p_value: float | None
    status: Literal["pass", "warning", "info", "unavailable"]
    sample_size: int | None
    message: str


class GroupSummaryResponse(BaseModel):
    label: str
    n: int
    mean: float | None
    median: float | None
    stddev: float | None


class VisualizationResponse(BaseModel):
    chart_type: str
    title: str
    x_label: str | None
    y_label: str | None
    data: list[dict[str, Any]]
    metadata: dict[str, Any]


class AnalysisResponse(BaseModel):
    version_id: UUID
    test_id: TestId
    test_name: str
    null_hypothesis: str
    alternative: Alternative
    alpha: float
    sample_size: int
    estimate: EstimateResponse | None
    confidence_interval: ConfidenceIntervalResponse | None
    statistic: StatisticResponse
    p_value: float
    significant: bool
    effect_size: EffectSizeResponse | None
    group_summaries: list[GroupSummaryResponse]
    diagnostics: list[DiagnosticResponse]
    visualizations: list[VisualizationResponse]
    warnings: list[str]
    interpretation: str


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _invalid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/datasets/versions/{version_id}/analyze/recommendations",
    response_model=RecommendationResponse,
)
def recommendations(
    version_id: UUID,
    payload: RecommendationRequest,
) -> RecommendationResponse:
    try:
        result = get_analyze_service().recommend(
            version_id,
            payload.goal,
            outcome_column_id=payload.outcome_column_id,
            group_column_id=payload.group_column_id,
            secondary_column_id=payload.secondary_column_id,
        )
    except ControlPlaneError as exc:
        raise _not_found(exc) from exc
    except (AnalyzeValidationError, duckdb.Error) as exc:
        raise _invalid(exc) from exc
    return RecommendationResponse(
        version_id=result.version_id,
        goal=result.goal,
        recommendations=[
            RecommendationItemResponse(
                test_id=item.test_id,
                name=item.name,
                preferred=item.preferred,
                rationale=item.rationale,
                assumptions=list(item.assumptions),
            )
            for item in result.recommendations
        ],
        notes=list(result.notes),
    )


@router.post(
    "/datasets/versions/{version_id}/analyze/run",
    response_model=AnalysisResponse,
)
def run_analysis(
    version_id: UUID,
    payload: AnalysisRunRequest,
) -> AnalysisResponse:
    try:
        result = get_analyze_service().run(
            version_id,
            payload.test_id,
            x_column_id=payload.x_column_id,
            y_column_id=payload.y_column_id,
            group_column_id=payload.group_column_id,
            reference_value=payload.reference_value,
            confidence_level=payload.confidence_level,
            alternative=payload.alternative,
        )
    except ControlPlaneError as exc:
        raise _not_found(exc) from exc
    except (AnalyzeValidationError, duckdb.Error, ValueError) as exc:
        raise _invalid(exc) from exc

    return AnalysisResponse(
        version_id=result.version_id,
        test_id=result.test_id,
        test_name=result.test_name,
        null_hypothesis=result.null_hypothesis,
        alternative=result.alternative,
        alpha=result.alpha,
        sample_size=result.sample_size,
        estimate=(
            EstimateResponse(**result.estimate.__dict__) if result.estimate else None
        ),
        confidence_interval=(
            ConfidenceIntervalResponse(**result.confidence_interval.__dict__)
            if result.confidence_interval
            else None
        ),
        statistic=StatisticResponse(**result.statistic.__dict__),
        p_value=result.p_value,
        significant=result.significant,
        effect_size=(
            EffectSizeResponse(**result.effect_size.__dict__)
            if result.effect_size
            else None
        ),
        group_summaries=[
            GroupSummaryResponse(**item.__dict__) for item in result.group_summaries
        ],
        diagnostics=[
            DiagnosticResponse(**item.__dict__) for item in result.diagnostics
        ],
        visualizations=[
            VisualizationResponse(
                chart_type=item.chart_type,
                title=item.title,
                x_label=item.x_label,
                y_label=item.y_label,
                data=list(item.data),
                metadata=item.metadata,
            )
            for item in result.visualizations
        ],
        warnings=list(result.warnings),
        interpretation=result.interpretation,
    )

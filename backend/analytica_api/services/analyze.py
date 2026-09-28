from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from uuid import UUID

import duckdb
import numpy as np
from scipy import stats

from analytica_api.domain.datasets import DatasetColumn, DatasetSchema
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef

_NUMERIC_TYPES = {"integer", "float"}
_CATEGORY_TYPES = {"boolean", "string", "categorical"}
_MAX_INTERACTIVE_ROWS = 250_000
_MAX_GROUPS = 50
_SHAPIRO_LIMIT = 5_000
_DIAGNOSTIC_LIMIT = 3_000

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


@dataclass(frozen=True)
class TestRecommendation:
    test_id: TestId
    name: str
    preferred: bool
    rationale: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationResult:
    version_id: UUID
    goal: AnalysisGoal
    recommendations: tuple[TestRecommendation, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Estimate:
    name: str
    value: float


@dataclass(frozen=True)
class ConfidenceInterval:
    level: float
    low: float | None
    high: float | None
    label: str


@dataclass(frozen=True)
class TestStatistic:
    name: str
    value: float
    degrees_of_freedom: float | None


@dataclass(frozen=True)
class EffectSize:
    name: str
    value: float
    magnitude: str | None


@dataclass(frozen=True)
class Diagnostic:
    name: str
    statistic: float | None
    p_value: float | None
    status: Literal["pass", "warning", "info", "unavailable"]
    sample_size: int | None
    message: str


@dataclass(frozen=True)
class GroupSummary:
    label: str
    n: int
    mean: float | None
    median: float | None
    stddev: float | None


@dataclass(frozen=True)
class DiagnosticVisualization:
    chart_type: str
    title: str
    x_label: str | None
    y_label: str | None
    data: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AnalysisResult:
    version_id: UUID
    test_id: TestId
    test_name: str
    null_hypothesis: str
    alternative: Alternative
    alpha: float
    sample_size: int
    estimate: Estimate | None
    confidence_interval: ConfidenceInterval | None
    statistic: TestStatistic
    p_value: float
    significant: bool
    effect_size: EffectSize | None
    group_summaries: tuple[GroupSummary, ...]
    diagnostics: tuple[Diagnostic, ...]
    visualizations: tuple[DiagnosticVisualization, ...]
    warnings: tuple[str, ...]
    interpretation: str


class AnalyzeValidationError(ValueError):
    pass


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _magnitude(value: float, *, kind: str) -> str | None:
    absolute = abs(value)
    if kind == "standardized_mean":
        if absolute < 0.2:
            return "very small"
        if absolute < 0.5:
            return "small"
        if absolute < 0.8:
            return "medium"
        return "large"
    if kind == "correlation":
        if absolute < 0.1:
            return "very small"
        if absolute < 0.3:
            return "small"
        if absolute < 0.5:
            return "medium"
        return "large"
    return None


def _summary(label: str, values: np.ndarray) -> GroupSummary:
    if values.size == 0:
        return GroupSummary(label=label, n=0, mean=None, median=None, stddev=None)
    return GroupSummary(
        label=label,
        n=int(values.size),
        mean=float(np.mean(values)),
        median=float(np.median(values)),
        stddev=float(np.std(values, ddof=1)) if values.size > 1 else None,
    )


def _box_visualization(
    title: str,
    group_name: str,
    outcome_name: str,
    groups: list[tuple[str, np.ndarray]],
) -> DiagnosticVisualization:
    data: list[dict[str, Any]] = []
    for label, values in groups:
        if values.size == 0:
            continue
        data.append(
            {
                "category": label,
                "values": [
                    float(np.min(values)),
                    float(np.quantile(values, 0.25)),
                    float(np.median(values)),
                    float(np.quantile(values, 0.75)),
                    float(np.max(values)),
                ],
            }
        )
    return DiagnosticVisualization(
        chart_type="box",
        title=title,
        x_label=group_name,
        y_label=outcome_name,
        data=tuple(data),
        metadata={},
    )


def _qq_visualization(
    title: str,
    label: str,
    values: np.ndarray,
) -> DiagnosticVisualization | None:
    if values.size < 3:
        return None
    sample = values
    if sample.size > _SHAPIRO_LIMIT:
        indexes = np.linspace(0, sample.size - 1, _SHAPIRO_LIMIT, dtype=int)
        sample = np.sort(sample)[indexes]
    (theoretical, ordered), (slope, intercept, r_value) = stats.probplot(
        sample,
        dist="norm",
        fit=True,
    )
    data = tuple(
        {"x": float(x), "y": float(y)}
        for x, y in zip(theoretical, ordered, strict=True)
    )
    return DiagnosticVisualization(
        chart_type="qq",
        title=title,
        x_label="Theoretical quantile",
        y_label=label,
        data=data,
        metadata={
            "slope": float(slope),
            "intercept": float(intercept),
            "r": float(r_value),
            "sample_size": int(sample.size),
        },
    )


def _scatter_visualization(
    title: str,
    x_name: str,
    y_name: str,
    x: np.ndarray,
    y: np.ndarray,
) -> DiagnosticVisualization:
    if x.size > _DIAGNOSTIC_LIMIT:
        indexes = np.linspace(0, x.size - 1, _DIAGNOSTIC_LIMIT, dtype=int)
        x = x[indexes]
        y = y[indexes]
    data = tuple({"x": float(a), "y": float(b)} for a, b in zip(x, y, strict=True))
    return DiagnosticVisualization(
        chart_type="scatter",
        title=title,
        x_label=x_name,
        y_label=y_name,
        data=data,
        metadata={"sample_size": int(x.size)},
    )


def _shapiro(values: np.ndarray, label: str, alpha: float) -> Diagnostic:
    if values.size < 3:
        return Diagnostic(
            name=f"Normality · {label}",
            statistic=None,
            p_value=None,
            status="unavailable",
            sample_size=int(values.size),
            message="At least three observed values are required for Shapiro-Wilk.",
        )
    sample = values
    sampled = False
    if sample.size > _SHAPIRO_LIMIT:
        indexes = np.linspace(0, sample.size - 1, _SHAPIRO_LIMIT, dtype=int)
        sample = sample[indexes]
        sampled = True
    result = stats.shapiro(sample)
    p_value = float(result.pvalue)
    status: Literal["pass", "warning"] = "pass" if p_value >= alpha else "warning"
    qualifier = " on a bounded 5,000-value diagnostic sample" if sampled else ""
    return Diagnostic(
        name=f"Normality · {label}",
        statistic=float(result.statistic),
        p_value=p_value,
        status=status,
        sample_size=int(sample.size),
        message=(
            f"Shapiro-Wilk{qualifier}; p {'≥' if p_value >= alpha else '<'} "
            f"α ({alpha:.3f}). Treat this as a diagnostic, not a binary proof of normality."
        ),
    )


def _interpret(test_name: str, p_value: float, alpha: float) -> str:
    if p_value < alpha:
        return (
            f"At α={alpha:.3f}, {test_name} provides evidence against the null "
            "hypothesis. Interpret practical importance using the estimate, interval, "
            "effect size, and diagnostics rather than the p-value alone."
        )
    return (
        f"At α={alpha:.3f}, {test_name} does not provide sufficient evidence to "
        "reject the null hypothesis. This is not evidence that the null hypothesis "
        "is true; inspect uncertainty and statistical power before drawing conclusions."
    )


class DatasetAnalyzeService:
    """Read-only inferential analysis over one immutable dataset version."""

    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store

    @contextmanager
    def _connection(
        self,
        version_id: UUID,
    ) -> Iterator[tuple[Any, DatasetSchema, duckdb.DuckDBPyConnection, Path]]:
        version = self.control_plane.get_version(version_id)
        schema = DatasetSchema.model_validate(version.schema_snapshot)
        artifact = self.control_plane.get_artifact_for_version_kind(
            version_id,
            "canonical_dataset",
        )
        reference = StorageObjectRef(
            key=artifact.storage_key,
            byte_size=artifact.byte_size,
            content_type=artifact.content_type,
            checksum_sha256=artifact.checksum_sha256,
        )
        with TemporaryDirectory(prefix="analytica-analyze-") as directory:
            path = self.artifact_store.materialize(
                reference,
                Path(directory) / "dataset.parquet",
            )
            connection = duckdb.connect(database=":memory:")
            try:
                yield version, schema, connection, path
            finally:
                connection.close()

    def _column(self, schema: DatasetSchema, column_id: str) -> DatasetColumn:
        column = schema.by_id().get(column_id)
        if column is None:
            raise AnalyzeValidationError(f"unknown column_id: {column_id}")
        return column

    def _numeric(self, schema: DatasetSchema, column_id: str) -> DatasetColumn:
        column = self._column(schema, column_id)
        if column.data_type not in _NUMERIC_TYPES:
            raise AnalyzeValidationError(f"{column.display_name} must be numeric")
        return column

    def _categorical(self, schema: DatasetSchema, column_id: str) -> DatasetColumn:
        column = self._column(schema, column_id)
        if column.data_type not in _CATEGORY_TYPES:
            raise AnalyzeValidationError(f"{column.display_name} must be categorical")
        return column

    def _guard_rows(self, count: int) -> None:
        if count > _MAX_INTERACTIVE_ROWS:
            raise AnalyzeValidationError(
                "This test exceeds the 250,000-row interactive analysis envelope. "
                "Run it as deferred analytical compute instead of silently sampling "
                "inferential statistics."
            )

    def recommend(
        self,
        version_id: UUID,
        goal: AnalysisGoal,
        *,
        outcome_column_id: str | None = None,
        group_column_id: str | None = None,
        secondary_column_id: str | None = None,
    ) -> RecommendationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            notes: list[str] = [
                "Recommendations use variable roles and observed cardinality; they do not "
                "replace study-design judgment or domain assumptions."
            ]
            recommendations: list[TestRecommendation] = []

            if goal == "compare_groups":
                if not outcome_column_id or not group_column_id:
                    raise AnalyzeValidationError("choose a numeric outcome and group column")
                outcome = self._numeric(schema, outcome_column_id)
                group = self._categorical(schema, group_column_id)
                group_identifier = _quote(group.physical_name)
                count = int(
                    connection.execute(
                        f"SELECT COUNT(DISTINCT {group_identifier}) FROM read_parquet(?) "
                        f"WHERE {group_identifier} IS NOT NULL",
                        [str(path)],
                    ).fetchone()[0]
                )
                if count < 2:
                    raise AnalyzeValidationError("group column needs at least two levels")
                if count > _MAX_GROUPS:
                    raise AnalyzeValidationError("group column has too many levels for this test")
                if count == 2:
                    recommendations.extend(
                        [
                            TestRecommendation(
                                test_id="welch_t",
                                name="Welch independent t-test",
                                preferred=True,
                                rationale=(
                                    f"{outcome.display_name} is numeric and "
                                    f"{group.display_name} has two observed groups."
                                ),
                                assumptions=(
                                    "independent observations",
                                    "approximately normal group distributions for small samples",
                                ),
                            ),
                            TestRecommendation(
                                test_id="mann_whitney",
                                name="Mann-Whitney U",
                                preferred=False,
                                rationale="Rank-based alternative for two independent groups.",
                                assumptions=("independent observations",),
                            ),
                        ]
                    )
                else:
                    recommendations.extend(
                        [
                            TestRecommendation(
                                test_id="welch_anova",
                                name="Welch one-way ANOVA",
                                preferred=True,
                                rationale=(
                                    f"{outcome.display_name} is numeric and "
                                    f"{group.display_name} has {count} observed groups."
                                ),
                                assumptions=(
                                    "independent observations",
                                    "approximately normal group distributions for small samples",
                                ),
                            ),
                            TestRecommendation(
                                test_id="kruskal",
                                name="Kruskal-Wallis H",
                                preferred=False,
                                rationale="Rank-based alternative for three or more independent groups.",
                                assumptions=("independent observations",),
                            ),
                        ]
                    )
                notes.append(f"Observed non-missing group levels: {count}.")

            elif goal == "compare_paired":
                if not outcome_column_id or not secondary_column_id:
                    raise AnalyzeValidationError("choose two numeric paired columns")
                first = self._numeric(schema, outcome_column_id)
                second = self._numeric(schema, secondary_column_id)
                recommendations.extend(
                    [
                        TestRecommendation(
                            test_id="paired_t",
                            name="Paired t-test",
                            preferred=True,
                            rationale=(
                                f"Compare row-aligned values of {first.display_name} and "
                                f"{second.display_name}."
                            ),
                            assumptions=(
                                "paired observations are meaningfully aligned by row",
                                "paired differences are approximately normal",
                            ),
                        ),
                        TestRecommendation(
                            test_id="wilcoxon",
                            name="Wilcoxon signed-rank",
                            preferred=False,
                            rationale="Rank-based alternative for paired numeric measurements.",
                            assumptions=("paired differences are symmetrically distributed",),
                        ),
                    ]
                )

            elif goal == "numeric_relationship":
                if not outcome_column_id or not secondary_column_id:
                    raise AnalyzeValidationError("choose two numeric columns")
                first = self._numeric(schema, outcome_column_id)
                second = self._numeric(schema, secondary_column_id)
                recommendations.extend(
                    [
                        TestRecommendation(
                            test_id="pearson",
                            name="Pearson correlation",
                            preferred=True,
                            rationale=(
                                f"Measure linear association between {first.display_name} and "
                                f"{second.display_name}."
                            ),
                            assumptions=("approximately linear relationship",),
                        ),
                        TestRecommendation(
                            test_id="spearman",
                            name="Spearman rank correlation",
                            preferred=False,
                            rationale="Monotonic rank-based association with fewer distributional assumptions.",
                            assumptions=("monotonic relationship",),
                        ),
                    ]
                )

            elif goal == "categorical_association":
                if not outcome_column_id or not secondary_column_id:
                    raise AnalyzeValidationError("choose two categorical columns")
                first = self._categorical(schema, outcome_column_id)
                second = self._categorical(schema, secondary_column_id)
                recommendations.append(
                    TestRecommendation(
                        test_id="chi_square",
                        name="Pearson chi-square test of independence",
                        preferred=True,
                        rationale=(
                            f"Test association between {first.display_name} and "
                            f"{second.display_name}."
                        ),
                        assumptions=("independent observations", "adequate expected cell counts"),
                    )
                )

            elif goal == "one_sample":
                if not outcome_column_id:
                    raise AnalyzeValidationError("choose a numeric outcome")
                outcome = self._numeric(schema, outcome_column_id)
                recommendations.append(
                    TestRecommendation(
                        test_id="one_sample_t",
                        name="One-sample t-test",
                        preferred=True,
                        rationale=(
                            f"Compare the mean of {outcome.display_name} with a reference value."
                        ),
                        assumptions=("approximately normal observations for small samples",),
                    )
                )
            else:
                raise AnalyzeValidationError(f"unsupported analysis goal: {goal}")

        return RecommendationResult(
            version_id=version.id,
            goal=goal,
            recommendations=tuple(recommendations),
            notes=tuple(notes),
        )

    def run(
        self,
        version_id: UUID,
        test_id: TestId,
        *,
        x_column_id: str,
        y_column_id: str | None = None,
        group_column_id: str | None = None,
        reference_value: float | None = None,
        confidence_level: float = 0.95,
        alternative: Alternative = "two-sided",
    ) -> AnalysisResult:
        if not 0.8 <= confidence_level < 1:
            raise AnalyzeValidationError("confidence_level must be between 0.8 and 1")
        alpha = 1 - confidence_level
        if test_id in {"welch_t", "welch_anova", "mann_whitney", "kruskal"}:
            if not group_column_id:
                raise AnalyzeValidationError("this test requires a group column")
            return self._run_group_test(
                version_id,
                test_id,
                x_column_id,
                group_column_id,
                confidence_level,
                alternative,
                alpha,
            )
        if test_id in {"paired_t", "wilcoxon", "pearson", "spearman", "chi_square"}:
            if not y_column_id:
                raise AnalyzeValidationError("this test requires a second column")
            return self._run_pair_test(
                version_id,
                test_id,
                x_column_id,
                y_column_id,
                confidence_level,
                alternative,
                alpha,
            )
        if test_id == "one_sample_t":
            if reference_value is None:
                raise AnalyzeValidationError("one-sample t-test requires a reference value")
            return self._run_one_sample(
                version_id,
                x_column_id,
                reference_value,
                confidence_level,
                alternative,
                alpha,
            )
        raise AnalyzeValidationError(f"unsupported test: {test_id}")

    def _grouped_values(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: Path,
        outcome: DatasetColumn,
        group: DatasetColumn,
    ) -> list[tuple[str, np.ndarray]]:
        outcome_identifier = _quote(outcome.physical_name)
        group_identifier = _quote(group.physical_name)
        rows = connection.execute(
            f"SELECT {group_identifier}, {outcome_identifier} FROM read_parquet(?) "
            f"WHERE {group_identifier} IS NOT NULL AND {outcome_identifier} IS NOT NULL "
            f"ORDER BY {group_identifier}",
            [str(path)],
        ).fetchall()
        self._guard_rows(len(rows))
        grouped: dict[str, list[float]] = {}
        for label, value in rows:
            grouped.setdefault(str(label), []).append(float(value))
        if len(grouped) < 2:
            raise AnalyzeValidationError("at least two non-empty groups are required")
        if len(grouped) > _MAX_GROUPS:
            raise AnalyzeValidationError("too many groups for interactive inference")
        return [(label, np.asarray(values, dtype=float)) for label, values in grouped.items()]

    def _run_group_test(
        self,
        version_id: UUID,
        test_id: TestId,
        x_column_id: str,
        group_column_id: str,
        confidence_level: float,
        alternative: Alternative,
        alpha: float,
    ) -> AnalysisResult:
        with self._connection(version_id) as (version, schema, connection, path):
            outcome = self._numeric(schema, x_column_id)
            group = self._categorical(schema, group_column_id)
            groups = self._grouped_values(connection, path, outcome, group)

        summaries = tuple(_summary(label, values) for label, values in groups)
        box = _box_visualization(
            f"{outcome.display_name} by {group.display_name}",
            group.display_name,
            outcome.display_name,
            groups,
        )
        total_n = sum(values.size for _, values in groups)
        warnings: list[str] = []

        if test_id in {"welch_t", "mann_whitney"} and len(groups) != 2:
            raise AnalyzeValidationError(f"{test_id} requires exactly two observed groups")
        if test_id in {"welch_anova", "kruskal"} and len(groups) < 3:
            raise AnalyzeValidationError(f"{test_id} requires at least three observed groups")

        if test_id == "welch_t":
            (label_a, a), (label_b, b) = groups
            if min(a.size, b.size) < 2:
                raise AnalyzeValidationError("Welch t-test needs at least two values per group")
            result = stats.ttest_ind(a, b, equal_var=False, alternative=alternative)
            interval = result.confidence_interval(confidence_level=confidence_level)
            pooled_variance = (
                ((a.size - 1) * np.var(a, ddof=1) + (b.size - 1) * np.var(b, ddof=1))
                / (a.size + b.size - 2)
            )
            pooled_sd = math.sqrt(float(pooled_variance)) if pooled_variance > 0 else 0.0
            cohen_d = (float(np.mean(a)) - float(np.mean(b))) / pooled_sd if pooled_sd else 0.0
            correction = 1 - 3 / (4 * (a.size + b.size) - 9)
            hedges_g = cohen_d * correction
            residuals = np.concatenate((a - np.mean(a), b - np.mean(b)))
            qq = _qq_visualization("Group-centered residual Q-Q", "Residual", residuals)
            levene = stats.levene(a, b, center="median")
            diagnostics = [
                _shapiro(a, label_a, alpha),
                _shapiro(b, label_b, alpha),
                Diagnostic(
                    name="Variance equality · Brown-Forsythe/Levene",
                    statistic=float(levene.statistic),
                    p_value=float(levene.pvalue),
                    status="info" if float(levene.pvalue) >= alpha else "warning",
                    sample_size=int(total_n),
                    message=(
                        "Welch's test does not require equal variances; this diagnostic is "
                        "reported to describe heteroscedasticity."
                    ),
                ),
            ]
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Welch independent t-test",
                null_hypothesis=f"Mean({label_a}) = Mean({label_b})",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(total_n),
                estimate=Estimate(
                    name=f"Mean difference · {label_a} − {label_b}",
                    value=float(np.mean(a) - np.mean(b)),
                ),
                confidence_interval=ConfidenceInterval(
                    level=confidence_level,
                    low=_finite(interval.low),
                    high=_finite(interval.high),
                    label="Difference in population means",
                ),
                statistic=TestStatistic(
                    name="t",
                    value=float(result.statistic),
                    degrees_of_freedom=_finite(result.df),
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Hedges' g",
                    value=float(hedges_g),
                    magnitude=_magnitude(hedges_g, kind="standardized_mean"),
                ),
                group_summaries=summaries,
                diagnostics=tuple(diagnostics),
                visualizations=(box,) + ((qq,) if qq else ()),
                warnings=tuple(warnings),
                interpretation=_interpret(
                    "Welch independent t-test",
                    float(result.pvalue),
                    alpha,
                ),
            )

        if test_id == "mann_whitney":
            (label_a, a), (label_b, b) = groups
            result = stats.mannwhitneyu(a, b, alternative=alternative, method="auto")
            rank_biserial = 2 * float(result.statistic) / (a.size * b.size) - 1
            warnings.append(
                "Mann-Whitney compares distributions; interpreting it purely as a median "
                "test requires additional shape assumptions."
            )
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Mann-Whitney U",
                null_hypothesis=f"{label_a} and {label_b} have the same distribution",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(total_n),
                estimate=Estimate(
                    name=f"Median difference · {label_a} − {label_b}",
                    value=float(np.median(a) - np.median(b)),
                ),
                confidence_interval=None,
                statistic=TestStatistic(
                    name="U",
                    value=float(result.statistic),
                    degrees_of_freedom=None,
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Rank-biserial correlation",
                    value=rank_biserial,
                    magnitude=_magnitude(rank_biserial, kind="correlation"),
                ),
                group_summaries=summaries,
                diagnostics=(
                    Diagnostic(
                        name="Distributional form",
                        statistic=None,
                        p_value=None,
                        status="info",
                        sample_size=int(total_n),
                        message="Inspect the linked box plot for distribution shape and spread.",
                    ),
                ),
                visualizations=(box,),
                warnings=tuple(warnings),
                interpretation=_interpret("Mann-Whitney U", float(result.pvalue), alpha),
            )

        values = [item[1] for item in groups]
        if test_id == "welch_anova":
            if any(group_values.size < 2 for group_values in values):
                raise AnalyzeValidationError("Welch ANOVA needs at least two values per group")
            result = stats.f_oneway(*values, equal_var=False)
            grand_mean = float(np.mean(np.concatenate(values)))
            ss_between = sum(
                group_values.size * (float(np.mean(group_values)) - grand_mean) ** 2
                for group_values in values
            )
            all_values = np.concatenate(values)
            ss_total = float(np.sum((all_values - grand_mean) ** 2))
            eta_squared = float(ss_between / ss_total) if ss_total > 0 else 0.0
            residuals = np.concatenate(
                [group_values - np.mean(group_values) for group_values in values]
            )
            qq = _qq_visualization("Group-centered residual Q-Q", "Residual", residuals)
            levene = stats.levene(*values, center="median")
            diagnostics = [
                *[_shapiro(group_values, label, alpha) for label, group_values in groups],
                Diagnostic(
                    name="Variance equality · Brown-Forsythe/Levene",
                    statistic=float(levene.statistic),
                    p_value=float(levene.pvalue),
                    status="info" if float(levene.pvalue) >= alpha else "warning",
                    sample_size=int(total_n),
                    message=(
                        "Welch ANOVA does not require equal variances; this diagnostic "
                        "describes heteroscedasticity."
                    ),
                ),
            ]
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Welch one-way ANOVA",
                null_hypothesis="All group population means are equal",
                alternative="two-sided",
                alpha=alpha,
                sample_size=int(total_n),
                estimate=None,
                confidence_interval=None,
                statistic=TestStatistic(
                    name="F",
                    value=float(result.statistic),
                    degrees_of_freedom=None,
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Eta-squared (descriptive)",
                    value=eta_squared,
                    magnitude=None,
                ),
                group_summaries=summaries,
                diagnostics=tuple(diagnostics),
                visualizations=(box,) + ((qq,) if qq else ()),
                warnings=(
                    "The reported eta-squared is a descriptive variance-explained measure; "
                    "the hypothesis test itself uses Welch's unequal-variance ANOVA.",
                ),
                interpretation=_interpret("Welch one-way ANOVA", float(result.pvalue), alpha),
            )

        if test_id == "kruskal":
            result = stats.kruskal(*values)
            epsilon_squared = (
                (float(result.statistic) - len(values) + 1) / (total_n - len(values))
                if total_n > len(values)
                else 0.0
            )
            epsilon_squared = max(0.0, float(epsilon_squared))
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Kruskal-Wallis H",
                null_hypothesis="All groups have the same distribution",
                alternative="two-sided",
                alpha=alpha,
                sample_size=int(total_n),
                estimate=None,
                confidence_interval=None,
                statistic=TestStatistic(
                    name="H",
                    value=float(result.statistic),
                    degrees_of_freedom=float(len(values) - 1),
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Epsilon-squared",
                    value=epsilon_squared,
                    magnitude=None,
                ),
                group_summaries=summaries,
                diagnostics=(
                    Diagnostic(
                        name="Distributional form",
                        statistic=None,
                        p_value=None,
                        status="info",
                        sample_size=int(total_n),
                        message="Inspect group distributions before interpreting H as a location effect.",
                    ),
                ),
                visualizations=(box,),
                warnings=(
                    "Kruskal-Wallis detects distributional differences; a significant result "
                    "does not identify which groups differ.",
                ),
                interpretation=_interpret("Kruskal-Wallis H", float(result.pvalue), alpha),
            )

        raise AnalyzeValidationError(f"unsupported group test: {test_id}")

    def _numeric_pair(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: Path,
        first: DatasetColumn,
        second: DatasetColumn,
    ) -> tuple[np.ndarray, np.ndarray]:
        first_identifier = _quote(first.physical_name)
        second_identifier = _quote(second.physical_name)
        rows = connection.execute(
            f"SELECT {first_identifier}, {second_identifier} FROM read_parquet(?) "
            f"WHERE {first_identifier} IS NOT NULL AND {second_identifier} IS NOT NULL",
            [str(path)],
        ).fetchall()
        self._guard_rows(len(rows))
        if len(rows) < 2:
            raise AnalyzeValidationError("at least two complete row pairs are required")
        return (
            np.asarray([float(row[0]) for row in rows], dtype=float),
            np.asarray([float(row[1]) for row in rows], dtype=float),
        )

    def _run_pair_test(
        self,
        version_id: UUID,
        test_id: TestId,
        x_column_id: str,
        y_column_id: str,
        confidence_level: float,
        alternative: Alternative,
        alpha: float,
    ) -> AnalysisResult:
        if test_id == "chi_square":
            return self._run_chi_square(
                version_id,
                x_column_id,
                y_column_id,
                confidence_level,
                alpha,
            )

        with self._connection(version_id) as (version, schema, connection, path):
            first = self._numeric(schema, x_column_id)
            second = self._numeric(schema, y_column_id)
            x, y = self._numeric_pair(connection, path, first, second)

        if test_id == "paired_t":
            differences = x - y
            if differences.size < 2:
                raise AnalyzeValidationError("paired t-test needs at least two complete pairs")
            result = stats.ttest_rel(x, y, alternative=alternative)
            interval = result.confidence_interval(confidence_level=confidence_level)
            sd_diff = float(np.std(differences, ddof=1))
            effect = float(np.mean(differences) / sd_diff) if sd_diff else 0.0
            qq = _qq_visualization("Paired-difference Q-Q", "Paired difference", differences)
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Paired t-test",
                null_hypothesis=f"Mean({first.display_name} − {second.display_name}) = 0",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(x.size),
                estimate=Estimate(
                    name=f"Mean paired difference · {first.display_name} − {second.display_name}",
                    value=float(np.mean(differences)),
                ),
                confidence_interval=ConfidenceInterval(
                    level=confidence_level,
                    low=_finite(interval.low),
                    high=_finite(interval.high),
                    label="Mean paired difference",
                ),
                statistic=TestStatistic(
                    name="t",
                    value=float(result.statistic),
                    degrees_of_freedom=_finite(result.df),
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Cohen's dz",
                    value=effect,
                    magnitude=_magnitude(effect, kind="standardized_mean"),
                ),
                group_summaries=(
                    _summary(first.display_name, x),
                    _summary(second.display_name, y),
                ),
                diagnostics=(_shapiro(differences, "paired differences", alpha),),
                visualizations=((qq,) if qq else ()),
                warnings=(),
                interpretation=_interpret("Paired t-test", float(result.pvalue), alpha),
            )

        if test_id == "wilcoxon":
            differences = x - y
            nonzero = differences[differences != 0]
            if nonzero.size == 0:
                raise AnalyzeValidationError("all paired differences are zero")
            result = stats.wilcoxon(differences, alternative=alternative, method="auto")
            ranks = stats.rankdata(np.abs(nonzero))
            positive = float(np.sum(ranks[nonzero > 0]))
            negative = float(np.sum(ranks[nonzero < 0]))
            denominator = positive + negative
            rank_biserial = (positive - negative) / denominator if denominator else 0.0
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Wilcoxon signed-rank",
                null_hypothesis="The paired-difference distribution is centered at zero",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(x.size),
                estimate=Estimate(
                    name="Median paired difference",
                    value=float(np.median(differences)),
                ),
                confidence_interval=None,
                statistic=TestStatistic(
                    name="W",
                    value=float(result.statistic),
                    degrees_of_freedom=None,
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Matched-pairs rank-biserial correlation",
                    value=float(rank_biserial),
                    magnitude=_magnitude(rank_biserial, kind="correlation"),
                ),
                group_summaries=(
                    _summary(first.display_name, x),
                    _summary(second.display_name, y),
                ),
                diagnostics=(
                    Diagnostic(
                        name="Paired design",
                        statistic=None,
                        p_value=None,
                        status="info",
                        sample_size=int(x.size),
                        message=(
                            "Rows are treated as matched pairs. Confirm row alignment reflects "
                            "the study design."
                        ),
                    ),
                ),
                visualizations=(),
                warnings=(
                    "Wilcoxon signed-rank assumes a meaningful paired design and a roughly "
                    "symmetric paired-difference distribution for location interpretation.",
                ),
                interpretation=_interpret("Wilcoxon signed-rank", float(result.pvalue), alpha),
            )

        if test_id == "pearson":
            result = stats.pearsonr(x, y, alternative=alternative)
            interval = result.confidence_interval(confidence_level=confidence_level)
            scatter = _scatter_visualization(
                f"{second.display_name} vs {first.display_name}",
                first.display_name,
                second.display_name,
                x,
                y,
            )
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Pearson correlation",
                null_hypothesis="Population Pearson correlation is zero",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(x.size),
                estimate=Estimate(name="Pearson r", value=float(result.statistic)),
                confidence_interval=ConfidenceInterval(
                    level=confidence_level,
                    low=_finite(interval.low),
                    high=_finite(interval.high),
                    label="Population correlation",
                ),
                statistic=TestStatistic(
                    name="r",
                    value=float(result.statistic),
                    degrees_of_freedom=float(x.size - 2),
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Pearson r",
                    value=float(result.statistic),
                    magnitude=_magnitude(float(result.statistic), kind="correlation"),
                ),
                group_summaries=(),
                diagnostics=(
                    _shapiro(x, first.display_name, alpha),
                    _shapiro(y, second.display_name, alpha),
                    Diagnostic(
                        name="Linearity",
                        statistic=None,
                        p_value=None,
                        status="info",
                        sample_size=int(x.size),
                        message="Inspect the linked scatter plot for linear form and outliers.",
                    ),
                ),
                visualizations=(scatter,),
                warnings=(),
                interpretation=_interpret("Pearson correlation", float(result.pvalue), alpha),
            )

        if test_id == "spearman":
            result = stats.spearmanr(x, y, alternative=alternative)
            scatter = _scatter_visualization(
                f"{second.display_name} vs {first.display_name}",
                first.display_name,
                second.display_name,
                x,
                y,
            )
            return AnalysisResult(
                version_id=version.id,
                test_id=test_id,
                test_name="Spearman rank correlation",
                null_hypothesis="Population Spearman rank correlation is zero",
                alternative=alternative,
                alpha=alpha,
                sample_size=int(x.size),
                estimate=Estimate(name="Spearman rho", value=float(result.statistic)),
                confidence_interval=None,
                statistic=TestStatistic(
                    name="ρ",
                    value=float(result.statistic),
                    degrees_of_freedom=None,
                ),
                p_value=float(result.pvalue),
                significant=float(result.pvalue) < alpha,
                effect_size=EffectSize(
                    name="Spearman rho",
                    value=float(result.statistic),
                    magnitude=_magnitude(float(result.statistic), kind="correlation"),
                ),
                group_summaries=(),
                diagnostics=(
                    Diagnostic(
                        name="Monotonic form",
                        statistic=None,
                        p_value=None,
                        status="info",
                        sample_size=int(x.size),
                        message="Inspect the linked scatter plot for monotonic form and outliers.",
                    ),
                ),
                visualizations=(scatter,),
                warnings=(),
                interpretation=_interpret(
                    "Spearman rank correlation",
                    float(result.pvalue),
                    alpha,
                ),
            )

        raise AnalyzeValidationError(f"unsupported paired/relationship test: {test_id}")

    def _run_one_sample(
        self,
        version_id: UUID,
        x_column_id: str,
        reference_value: float,
        confidence_level: float,
        alternative: Alternative,
        alpha: float,
    ) -> AnalysisResult:
        with self._connection(version_id) as (version, schema, connection, path):
            column = self._numeric(schema, x_column_id)
            identifier = _quote(column.physical_name)
            rows = connection.execute(
                f"SELECT {identifier} FROM read_parquet(?) WHERE {identifier} IS NOT NULL",
                [str(path)],
            ).fetchall()
        self._guard_rows(len(rows))
        values = np.asarray([float(row[0]) for row in rows], dtype=float)
        if values.size < 2:
            raise AnalyzeValidationError("one-sample t-test needs at least two observations")
        result = stats.ttest_1samp(values, reference_value, alternative=alternative)
        interval = result.confidence_interval(confidence_level=confidence_level)
        sd = float(np.std(values, ddof=1))
        effect = (float(np.mean(values)) - reference_value) / sd if sd else 0.0
        qq = _qq_visualization("One-sample Q-Q", column.display_name, values)
        return AnalysisResult(
            version_id=version.id,
            test_id="one_sample_t",
            test_name="One-sample t-test",
            null_hypothesis=f"Population mean = {reference_value:g}",
            alternative=alternative,
            alpha=alpha,
            sample_size=int(values.size),
            estimate=Estimate(
                name="Mean difference from reference",
                value=float(np.mean(values) - reference_value),
            ),
            confidence_interval=ConfidenceInterval(
                level=confidence_level,
                low=_finite(interval.low),
                high=_finite(interval.high),
                label="Population mean",
            ),
            statistic=TestStatistic(
                name="t",
                value=float(result.statistic),
                degrees_of_freedom=_finite(result.df),
            ),
            p_value=float(result.pvalue),
            significant=float(result.pvalue) < alpha,
            effect_size=EffectSize(
                name="Cohen's d",
                value=float(effect),
                magnitude=_magnitude(effect, kind="standardized_mean"),
            ),
            group_summaries=(_summary(column.display_name, values),),
            diagnostics=(_shapiro(values, column.display_name, alpha),),
            visualizations=((qq,) if qq else ()),
            warnings=(),
            interpretation=_interpret("One-sample t-test", float(result.pvalue), alpha),
        )

    def _run_chi_square(
        self,
        version_id: UUID,
        x_column_id: str,
        y_column_id: str,
        confidence_level: float,
        alpha: float,
    ) -> AnalysisResult:
        with self._connection(version_id) as (version, schema, connection, path):
            first = self._categorical(schema, x_column_id)
            second = self._categorical(schema, y_column_id)
            first_identifier = _quote(first.physical_name)
            second_identifier = _quote(second.physical_name)
            rows = connection.execute(
                f"SELECT {first_identifier}, {second_identifier}, COUNT(*) AS n "
                "FROM read_parquet(?) "
                f"WHERE {first_identifier} IS NOT NULL AND {second_identifier} IS NOT NULL "
                f"GROUP BY {first_identifier}, {second_identifier} "
                f"ORDER BY {first_identifier}, {second_identifier}",
                [str(path)],
            ).fetchall()
        row_labels = list(dict.fromkeys(str(row[0]) for row in rows))
        column_labels = list(dict.fromkeys(str(row[1]) for row in rows))
        if len(row_labels) < 2 or len(column_labels) < 2:
            raise AnalyzeValidationError("chi-square needs at least two levels in each variable")
        if len(row_labels) > _MAX_GROUPS or len(column_labels) > _MAX_GROUPS:
            raise AnalyzeValidationError("contingency table is too large for interactive inference")
        observed = np.zeros((len(row_labels), len(column_labels)), dtype=float)
        row_index = {label: index for index, label in enumerate(row_labels)}
        column_index = {label: index for index, label in enumerate(column_labels)}
        for first_value, second_value, count in rows:
            observed[row_index[str(first_value)], column_index[str(second_value)]] = int(count)
        total_n = int(np.sum(observed))
        result = stats.chi2_contingency(observed, correction=False)
        expected = np.asarray(result.expected_freq, dtype=float)
        denominator = total_n * min(len(row_labels) - 1, len(column_labels) - 1)
        cramers_v = math.sqrt(float(result.statistic) / denominator) if denominator else 0.0
        residuals = np.divide(
            observed - expected,
            np.sqrt(expected),
            out=np.zeros_like(observed),
            where=expected > 0,
        )
        heatmap_data = tuple(
            {
                "x": column_label,
                "y": row_label,
                "value": float(residuals[row_position, column_position]),
            }
            for row_position, row_label in enumerate(row_labels)
            for column_position, column_label in enumerate(column_labels)
        )
        low_expected = int(np.sum(expected < 5))
        total_cells = int(expected.size)
        minimum_expected = float(np.min(expected))
        diagnostic_status: Literal["pass", "warning"] = (
            "warning" if low_expected else "pass"
        )
        diagnostic = Diagnostic(
            name="Expected cell counts",
            statistic=minimum_expected,
            p_value=None,
            status=diagnostic_status,
            sample_size=total_n,
            message=(
                f"Minimum expected count {minimum_expected:.3g}; {low_expected}/{total_cells} "
                "cells are below 5. Sparse tables can make the chi-square approximation less reliable."
            ),
        )
        return AnalysisResult(
            version_id=version.id,
            test_id="chi_square",
            test_name="Pearson chi-square test of independence",
            null_hypothesis=f"{first.display_name} and {second.display_name} are independent",
            alternative="two-sided",
            alpha=alpha,
            sample_size=total_n,
            estimate=None,
            confidence_interval=None,
            statistic=TestStatistic(
                name="χ²",
                value=float(result.statistic),
                degrees_of_freedom=float(result.dof),
            ),
            p_value=float(result.pvalue),
            significant=float(result.pvalue) < alpha,
            effect_size=EffectSize(
                name="Cramér's V",
                value=float(cramers_v),
                magnitude=None,
            ),
            group_summaries=(),
            diagnostics=(diagnostic,),
            visualizations=(
                DiagnosticVisualization(
                    chart_type="heatmap",
                    title="Standardized contingency residuals",
                    x_label=second.display_name,
                    y_label=first.display_name,
                    data=heatmap_data,
                    metadata={
                        "minimum_expected": minimum_expected,
                        "cells_below_five": low_expected,
                    },
                ),
            ),
            warnings=(
                "Yates continuity correction is not applied; the reported statistic is "
                "Pearson's chi-square statistic for the observed contingency table.",
            ),
            interpretation=_interpret(
                "Pearson chi-square test of independence",
                float(result.pvalue),
                alpha,
            ),
        )

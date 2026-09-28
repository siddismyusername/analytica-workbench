from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import duckdb
import numpy as np
from scipy import stats

from analytica_api.domain.datasets import DatasetColumn, DatasetSchema
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef

_NUMERIC_TYPES = {"integer", "float"}
_TEMPORAL_TYPES = {"date", "datetime"}
_CATEGORICAL_TYPES = {"boolean", "string", "categorical"}


@dataclass(frozen=True)
class DescriptiveResult:
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


@dataclass(frozen=True)
class FrequencyItem:
    value: Any | None
    count: int
    percentage: float


@dataclass(frozen=True)
class FrequencyResult:
    version_id: UUID
    column_id: str
    column_name: str
    items: tuple[FrequencyItem, ...]
    total_rows: int
    truncated: bool


@dataclass(frozen=True)
class CorrelationResult:
    version_id: UUID
    method: str
    columns: tuple[tuple[str, str], ...]
    matrix: tuple[tuple[float | None, ...], ...]


@dataclass(frozen=True)
class CrosstabResult:
    version_id: UUID
    row_column: tuple[str, str]
    column_column: tuple[str, str]
    row_values: tuple[Any | None, ...]
    column_values: tuple[Any | None, ...]
    counts: tuple[tuple[int, ...], ...]
    row_totals: tuple[int, ...]
    column_totals: tuple[int, ...]
    total: int
    row_truncated: bool
    column_truncated: bool


@dataclass(frozen=True)
class VisualizationResult:
    version_id: UUID
    chart_type: str
    title: str
    x_label: str | None
    y_label: str | None
    data: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _percentage(count: int, total: int) -> float:
    return round((count / total) * 100, 4) if total else 0.0


class ExploreValidationError(ValueError):
    pass


class DatasetExploreService:
    """Read-only exploratory analysis over an immutable canonical dataset version."""

    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store

    def _context(self, version_id: UUID) -> tuple[Any, DatasetSchema, Any]:
        version = self.control_plane.get_version(version_id)
        schema = DatasetSchema.model_validate(version.schema_snapshot)
        artifact = self.control_plane.get_artifact_for_version_kind(
            version_id,
            "canonical_dataset",
        )
        return version, schema, artifact

    @contextmanager
    def _connection(
        self,
        version_id: UUID,
    ) -> Iterator[
        tuple[Any, DatasetSchema, duckdb.DuckDBPyConnection, Path]
    ]:
        version, schema, artifact = self._context(version_id)
        object_ref = StorageObjectRef(
            key=artifact.storage_key,
            byte_size=artifact.byte_size,
            content_type=artifact.content_type,
            checksum_sha256=artifact.checksum_sha256,
        )
        with TemporaryDirectory(prefix="analytica-explore-") as directory:
            path = self.artifact_store.materialize(
                object_ref,
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
            raise ExploreValidationError(f"unknown column_id: {column_id}")
        return column

    def _numeric_column(
        self,
        schema: DatasetSchema,
        column_id: str,
    ) -> DatasetColumn:
        column = self._column(schema, column_id)
        if column.data_type not in _NUMERIC_TYPES:
            raise ExploreValidationError(
                f"column {column.display_name} must be numeric"
            )
        return column

    def describe(self, version_id: UUID, column_id: str) -> DescriptiveResult:
        with self._connection(version_id) as (version, schema, connection, path):
            column = self._column(schema, column_id)
            identifier = _quote(column.physical_name)
            numeric = column.data_type in _NUMERIC_TYPES
            temporal = column.data_type in _TEMPORAL_TYPES
            metrics = [
                "COUNT(*)",
                f"COUNT({identifier})",
                f"APPROX_COUNT_DISTINCT({identifier})",
                f"MIN({identifier})",
                f"MAX({identifier})",
            ]
            if numeric:
                metrics.extend(
                    [
                        f"AVG({identifier})",
                        f"STDDEV_SAMP({identifier})",
                        f"QUANTILE_CONT({identifier}, 0.25)",
                        f"MEDIAN({identifier})",
                        f"QUANTILE_CONT({identifier}, 0.75)",
                    ]
                )
            row = connection.execute(
                f"SELECT {', '.join(metrics)} FROM read_parquet(?)",
                [str(path)],
            ).fetchone()
            if row is None:
                raise RuntimeError("descriptive query returned no row")
            mode_row = connection.execute(
                f"SELECT {identifier}, COUNT(*) AS n FROM read_parquet(?) "
                f"WHERE {identifier} IS NOT NULL GROUP BY {identifier} "
                "ORDER BY n DESC, 1 LIMIT 1",
                [str(path)],
            ).fetchone()

        row_count = int(row[0])
        valid_count = int(row[1])
        mean = float(row[5]) if numeric and row[5] is not None else None
        stddev = float(row[6]) if numeric and row[6] is not None else None
        q1 = float(row[7]) if numeric and row[7] is not None else None
        median = float(row[8]) if numeric and row[8] is not None else None
        q3 = float(row[9]) if numeric and row[9] is not None else None
        return DescriptiveResult(
            version_id=version.id,
            column_id=column.column_id,
            column_name=column.display_name,
            data_type=column.data_type,
            row_count=row_count,
            valid_count=valid_count,
            missing_count=row_count - valid_count,
            distinct_count=int(row[2]),
            minimum=_json_value(row[3]) if numeric or temporal else None,
            maximum=_json_value(row[4]) if numeric or temporal else None,
            mean=mean,
            stddev=stddev,
            q1=q1,
            median=median,
            q3=q3,
            mode=_json_value(mode_row[0]) if mode_row else None,
            mode_count=int(mode_row[1]) if mode_row else 0,
        )

    def frequencies(
        self,
        version_id: UUID,
        column_id: str,
        *,
        limit: int = 30,
    ) -> FrequencyResult:
        if not 1 <= limit <= 100:
            raise ExploreValidationError(
                "frequency limit must be between 1 and 100"
            )
        with self._connection(version_id) as (version, schema, connection, path):
            column = self._column(schema, column_id)
            identifier = _quote(column.physical_name)
            count_row = connection.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [str(path)],
            ).fetchone()
            total = int(count_row[0]) if count_row else 0
            rows = connection.execute(
                f"SELECT {identifier}, COUNT(*) AS n FROM read_parquet(?) "
                f"GROUP BY {identifier} ORDER BY n DESC, 1 LIMIT ?",
                [str(path), limit + 1],
            ).fetchall()

        truncated = len(rows) > limit
        return FrequencyResult(
            version_id=version.id,
            column_id=column.column_id,
            column_name=column.display_name,
            total_rows=total,
            truncated=truncated,
            items=tuple(
                FrequencyItem(
                    value=_json_value(value),
                    count=int(count),
                    percentage=_percentage(int(count), total),
                )
                for value, count in rows[:limit]
            ),
        )

    def correlation(
        self,
        version_id: UUID,
        column_ids: tuple[str, ...] | None = None,
    ) -> CorrelationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            if column_ids:
                columns = tuple(
                    self._numeric_column(schema, item) for item in column_ids
                )
            else:
                columns = tuple(
                    column
                    for column in schema.columns
                    if column.data_type in _NUMERIC_TYPES
                )
            if len(columns) < 2:
                raise ExploreValidationError(
                    "correlation requires at least two numeric columns"
                )
            if len(columns) > 20:
                raise ExploreValidationError(
                    "correlation supports at most 20 columns per query"
                )

            expressions: list[str] = []
            pairs: list[tuple[int, int]] = []
            for row_index, left in enumerate(columns):
                for column_index in range(row_index, len(columns)):
                    right = columns[column_index]
                    expressions.append(
                        f"CORR({_quote(left.physical_name)}, "
                        f"{_quote(right.physical_name)})"
                    )
                    pairs.append((row_index, column_index))
            values = connection.execute(
                f"SELECT {', '.join(expressions)} FROM read_parquet(?)",
                [str(path)],
            ).fetchone()

        if values is None:
            raise RuntimeError("correlation query returned no row")
        matrix: list[list[float | None]] = [
            [None for _ in columns] for _ in columns
        ]
        for (row_index, column_index), raw in zip(
            pairs,
            values,
            strict=True,
        ):
            numeric_value = float(raw) if raw is not None else math.nan
            value = numeric_value if math.isfinite(numeric_value) else None
            matrix[row_index][column_index] = value
            matrix[column_index][row_index] = value

        return CorrelationResult(
            version_id=version.id,
            method="pearson",
            columns=tuple(
                (column.column_id, column.display_name) for column in columns
            ),
            matrix=tuple(tuple(row) for row in matrix),
        )

    def crosstab(
        self,
        version_id: UUID,
        row_column_id: str,
        column_column_id: str,
        *,
        limit: int = 12,
    ) -> CrosstabResult:
        if row_column_id == column_column_id:
            raise ExploreValidationError("crosstab columns must be different")
        if not 2 <= limit <= 20:
            raise ExploreValidationError(
                "crosstab category limit must be between 2 and 20"
            )

        with self._connection(version_id) as (version, schema, connection, path):
            row_column = self._column(schema, row_column_id)
            column_column = self._column(schema, column_column_id)
            if (
                row_column.data_type not in _CATEGORICAL_TYPES
                or column_column.data_type not in _CATEGORICAL_TYPES
            ):
                raise ExploreValidationError("crosstab requires categorical columns")
            row_identifier = _quote(row_column.physical_name)
            column_identifier = _quote(column_column.physical_name)
            row_results = [
                item[0]
                for item in connection.execute(
                    f"SELECT {row_identifier}, COUNT(*) AS n "
                    "FROM read_parquet(?) "
                    f"WHERE {row_identifier} IS NOT NULL "
                    f"GROUP BY {row_identifier} ORDER BY n DESC LIMIT ?",
                    [str(path), limit + 1],
                ).fetchall()
            ]
            column_results = [
                item[0]
                for item in connection.execute(
                    f"SELECT {column_identifier}, COUNT(*) AS n "
                    "FROM read_parquet(?) "
                    f"WHERE {column_identifier} IS NOT NULL "
                    f"GROUP BY {column_identifier} ORDER BY n DESC LIMIT ?",
                    [str(path), limit + 1],
                ).fetchall()
            ]
            row_values = row_results[:limit]
            column_values = column_results[:limit]
            if not row_values or not column_values:
                raise ExploreValidationError(
                    "crosstab requires observed values in both columns"
                )
            row_placeholders = ", ".join("?" for _ in row_values)
            column_placeholders = ", ".join("?" for _ in column_values)
            rows = connection.execute(
                f"SELECT {row_identifier}, {column_identifier}, COUNT(*) AS n "
                "FROM read_parquet(?) "
                f"WHERE {row_identifier} IN ({row_placeholders}) "
                f"AND {column_identifier} IN ({column_placeholders}) "
                f"GROUP BY {row_identifier}, {column_identifier}",
                [str(path), *row_values, *column_values],
            ).fetchall()

        row_index = {value: index for index, value in enumerate(row_values)}
        column_index = {
            value: index for index, value in enumerate(column_values)
        }
        counts = [[0 for _ in column_values] for _ in row_values]
        for row_value, column_value, count in rows:
            counts[row_index[row_value]][column_index[column_value]] = int(count)
        row_totals = tuple(sum(row) for row in counts)
        column_totals = tuple(
            sum(counts[row][column] for row in range(len(counts)))
            for column in range(len(column_values))
        )
        return CrosstabResult(
            version_id=version.id,
            row_column=(row_column.column_id, row_column.display_name),
            column_column=(
                column_column.column_id,
                column_column.display_name,
            ),
            row_values=tuple(_json_value(value) for value in row_values),
            column_values=tuple(_json_value(value) for value in column_values),
            counts=tuple(tuple(row) for row in counts),
            row_totals=row_totals,
            column_totals=column_totals,
            total=sum(row_totals),
            row_truncated=len(row_results) > limit,
            column_truncated=len(column_results) > limit,
        )

    def visualization(
        self,
        version_id: UUID,
        chart_type: str,
        x_column_id: str,
        *,
        y_column_id: str | None = None,
        bins: int = 20,
        limit: int = 50,
    ) -> VisualizationResult:
        supported = {
            "histogram",
            "bar",
            "line",
            "scatter",
            "box",
            "heatmap",
            "qq",
        }
        if chart_type not in supported:
            raise ExploreValidationError(
                f"unsupported chart type: {chart_type}"
            )
        if not 5 <= bins <= 100:
            raise ExploreValidationError("bins must be between 5 and 100")
        if not 5 <= limit <= 5000:
            raise ExploreValidationError(
                "visualization limit must be between 5 and 5000"
            )
        if chart_type == "heatmap":
            return self._correlation_heatmap(version_id)
        if chart_type == "histogram":
            return self._histogram(version_id, x_column_id, bins)
        if chart_type == "bar":
            return self._bar(version_id, x_column_id, min(limit, 100))
        if chart_type == "box":
            return self._box(version_id, x_column_id, y_column_id)
        if chart_type == "qq":
            return self._qq(version_id, x_column_id, min(limit, 5000))
        if y_column_id is None:
            raise ExploreValidationError(
                f"{chart_type} requires a y column"
            )
        if chart_type == "scatter":
            return self._scatter(
                version_id,
                x_column_id,
                y_column_id,
                min(limit, 5000),
            )
        return self._line(
            version_id,
            x_column_id,
            y_column_id,
            min(limit, 1000),
        )

    def _histogram(
        self,
        version_id: UUID,
        column_id: str,
        bins: int,
    ) -> VisualizationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            column = self._numeric_column(schema, column_id)
            identifier = _quote(column.physical_name)
            bounds = connection.execute(
                f"SELECT MIN({identifier}), MAX({identifier}), "
                f"COUNT({identifier}) FROM read_parquet(?)",
                [str(path)],
            ).fetchone()
            if bounds is None or bounds[0] is None:
                data: tuple[dict[str, Any], ...] = ()
            else:
                minimum = float(bounds[0])
                maximum = float(bounds[1])
                if minimum == maximum:
                    data = (
                        {
                            "start": minimum,
                            "end": maximum,
                            "count": int(bounds[2]),
                        },
                    )
                else:
                    width = (maximum - minimum) / bins
                    rows = connection.execute(
                        f"SELECT LEAST(?, CAST(FLOOR(({identifier} - ?) / ?) "
                        "AS INTEGER)) AS bin, COUNT(*) "
                        "FROM read_parquet(?) "
                        f"WHERE {identifier} IS NOT NULL "
                        "GROUP BY bin ORDER BY bin",
                        [bins - 1, minimum, width, str(path)],
                    ).fetchall()
                    data = tuple(
                        {
                            "start": minimum + int(index) * width,
                            "end": minimum + (int(index) + 1) * width,
                            "count": int(count),
                        }
                        for index, count in rows
                    )
        return VisualizationResult(
            version_id=version.id,
            chart_type="histogram",
            title=f"Distribution of {column.display_name}",
            x_label=column.display_name,
            y_label="Count",
            data=data,
            metadata={"bins": bins},
        )

    def _bar(
        self,
        version_id: UUID,
        column_id: str,
        limit: int,
    ) -> VisualizationResult:
        result = self.frequencies(version_id, column_id, limit=limit)
        return VisualizationResult(
            version_id=result.version_id,
            chart_type="bar",
            title=f"Frequency of {result.column_name}",
            x_label=result.column_name,
            y_label="Count",
            data=tuple(
                {
                    "category": (
                        "(missing)" if item.value is None else str(item.value)
                    ),
                    "value": item.count,
                }
                for item in result.items
            ),
            metadata={"truncated": result.truncated},
        )

    def _line(
        self,
        version_id: UUID,
        x_column_id: str,
        y_column_id: str,
        limit: int,
    ) -> VisualizationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            x_column = self._column(schema, x_column_id)
            y_column = self._numeric_column(schema, y_column_id)
            if x_column.data_type not in _NUMERIC_TYPES | _TEMPORAL_TYPES:
                raise ExploreValidationError(
                    "line chart x column must be numeric or temporal"
                )
            x_identifier = _quote(x_column.physical_name)
            y_identifier = _quote(y_column.physical_name)
            rows = connection.execute(
                f"SELECT {x_identifier}, AVG({y_identifier}) AS value "
                "FROM read_parquet(?) "
                f"WHERE {x_identifier} IS NOT NULL "
                f"AND {y_identifier} IS NOT NULL "
                f"GROUP BY {x_identifier} ORDER BY {x_identifier} LIMIT ?",
                [str(path), limit],
            ).fetchall()
        return VisualizationResult(
            version_id=version.id,
            chart_type="line",
            title=f"{y_column.display_name} by {x_column.display_name}",
            x_label=x_column.display_name,
            y_label=y_column.display_name,
            data=tuple(
                {"x": _json_value(x), "y": float(y)} for x, y in rows
            ),
            metadata={"aggregation": "mean"},
        )

    def _scatter(
        self,
        version_id: UUID,
        x_column_id: str,
        y_column_id: str,
        limit: int,
    ) -> VisualizationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            x_column = self._numeric_column(schema, x_column_id)
            y_column = self._numeric_column(schema, y_column_id)
            x_identifier = _quote(x_column.physical_name)
            y_identifier = _quote(y_column.physical_name)
            rows = connection.execute(
                "WITH filtered AS ("
                f"SELECT {x_identifier}, {y_identifier} FROM read_parquet(?) "
                f"WHERE {x_identifier} IS NOT NULL "
                f"AND {y_identifier} IS NOT NULL) "
                f"SELECT * FROM filtered USING SAMPLE reservoir({limit} ROWS)",
                [str(path)],
            ).fetchall()
        return VisualizationResult(
            version_id=version.id,
            chart_type="scatter",
            title=f"{y_column.display_name} vs {x_column.display_name}",
            x_label=x_column.display_name,
            y_label=y_column.display_name,
            data=tuple(
                {"x": float(x), "y": float(y)} for x, y in rows
            ),
            metadata={"sample_size": len(rows)},
        )

    def _box(
        self,
        version_id: UUID,
        numeric_column_id: str,
        group_column_id: str | None,
    ) -> VisualizationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            numeric = self._numeric_column(schema, numeric_column_id)
            numeric_identifier = _quote(numeric.physical_name)
            if group_column_id is None:
                rows = connection.execute(
                    f"SELECT MIN({numeric_identifier}), "
                    f"QUANTILE_CONT({numeric_identifier}, 0.25), "
                    f"MEDIAN({numeric_identifier}), "
                    f"QUANTILE_CONT({numeric_identifier}, 0.75), "
                    f"MAX({numeric_identifier}) FROM read_parquet(?) "
                    f"WHERE {numeric_identifier} IS NOT NULL",
                    [str(path)],
                ).fetchall()
                data = tuple(
                    {
                        "category": numeric.display_name,
                        "values": [float(value) for value in row],
                    }
                    for row in rows
                    if all(value is not None for value in row)
                )
                title = f"Box plot of {numeric.display_name}"
            else:
                group = self._column(schema, group_column_id)
                group_identifier = _quote(group.physical_name)
                rows = connection.execute(
                    f"SELECT {group_identifier}, MIN({numeric_identifier}), "
                    f"QUANTILE_CONT({numeric_identifier}, 0.25), "
                    f"MEDIAN({numeric_identifier}), "
                    f"QUANTILE_CONT({numeric_identifier}, 0.75), "
                    f"MAX({numeric_identifier}), COUNT(*) AS n "
                    "FROM read_parquet(?) "
                    f"WHERE {numeric_identifier} IS NOT NULL "
                    f"GROUP BY {group_identifier} ORDER BY n DESC LIMIT 12",
                    [str(path)],
                ).fetchall()
                data = tuple(
                    {
                        "category": (
                            "(missing)" if row[0] is None else str(row[0])
                        ),
                        "values": [float(value) for value in row[1:6]],
                    }
                    for row in rows
                    if all(value is not None for value in row[1:6])
                )
                title = f"{numeric.display_name} by {group.display_name}"
        return VisualizationResult(
            version_id=version.id,
            chart_type="box",
            title=title,
            x_label="Group",
            y_label=numeric.display_name,
            data=data,
            metadata={},
        )

    def _qq(
        self,
        version_id: UUID,
        column_id: str,
        limit: int,
    ) -> VisualizationResult:
        with self._connection(version_id) as (version, schema, connection, path):
            column = self._numeric_column(schema, column_id)
            identifier = _quote(column.physical_name)
            rows = connection.execute(
                "WITH filtered AS ("
                f"SELECT {identifier} FROM read_parquet(?) "
                f"WHERE {identifier} IS NOT NULL) "
                f"SELECT * FROM filtered USING SAMPLE reservoir({limit} ROWS)",
                [str(path)],
            ).fetchall()
        sample = np.asarray([float(row[0]) for row in rows], dtype=float)
        if sample.size < 3:
            raise ExploreValidationError(
                "Q-Q plot requires at least three observed values"
            )
        probability = stats.probplot(sample, dist="norm", fit=True)
        (theoretical, ordered), (slope, intercept, r_value) = probability
        data = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(
                theoretical.tolist(),
                ordered.tolist(),
                strict=True,
            )
        )
        return VisualizationResult(
            version_id=version.id,
            chart_type="qq",
            title=f"Normal Q-Q · {column.display_name}",
            x_label="Theoretical quantiles",
            y_label=column.display_name,
            data=data,
            metadata={
                "slope": float(slope),
                "intercept": float(intercept),
                "r": float(r_value),
                "sample_size": int(sample.size),
            },
        )

    def _correlation_heatmap(
        self,
        version_id: UUID,
    ) -> VisualizationResult:
        result = self.correlation(version_id)
        data: list[dict[str, Any]] = []
        for row_index, (_, row_name) in enumerate(result.columns):
            for column_index, (_, column_name) in enumerate(result.columns):
                data.append(
                    {
                        "x": column_name,
                        "y": row_name,
                        "value": result.matrix[row_index][column_index],
                    }
                )
        return VisualizationResult(
            version_id=result.version_id,
            chart_type="heatmap",
            title="Pearson correlation matrix",
            x_label=None,
            y_label=None,
            data=tuple(data),
            metadata={"method": result.method},
        )

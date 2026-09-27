from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from analytica_api.config import Settings
from analytica_api.domain.datasets import DatasetColumn, DatasetSchema, DatasetSource
from analytica_api.execution.duckdb_engine import DuckDBEngine, PipelineCompiler
from analytica_api.operations.models import (
    DeduplicateOperation,
    DropColumnsOperation,
    FillNullOperation,
    FilterOperation,
    PipelineSpec,
)


def _schema() -> DatasetSchema:
    return DatasetSchema(
        columns=(
            DatasetColumn(
                column_id="col_age",
                physical_name="age",
                display_name="Age",
                data_type="integer",
            ),
            DatasetColumn(
                column_id="col_city",
                physical_name="city",
                display_name="City",
                data_type="string",
            ),
            DatasetColumn(
                column_id="col_secret",
                physical_name="secret",
                display_name="Secret",
                data_type="string",
            ),
        )
    )


def test_filter_value_is_parameterized() -> None:
    malicious_value = "x' OR TRUE --"
    pipeline = PipelineSpec(
        operations=(
            FilterOperation(
                operation_id="op_1",
                column_id="col_city",
                operator="eq",
                value=malicious_value,
            ),
        )
    )
    compiled = PipelineCompiler(_schema()).compile(
        DatasetSource(uri="/tmp/example.parquet"),
        pipeline,
    )

    assert malicious_value not in compiled.sql
    assert malicious_value in compiled.parameters


def test_pipeline_executes_against_parquet(tmp_path: Path) -> None:
    parquet_path = tmp_path / "dataset.parquet"
    pq.write_table(
        pa.table(
            {
                "age": [18, 25, 25],
                "city": ["Pune", None, None],
                "secret": ["x", "same", "same"],
            }
        ),
        parquet_path,
    )

    pipeline = PipelineSpec(
        operations=(
            FilterOperation(
                operation_id="op_filter",
                column_id="col_age",
                operator="gte",
                value=20,
            ),
            FillNullOperation(
                operation_id="op_fill",
                column_id="col_city",
                value="Unknown",
            ),
            DropColumnsOperation(
                operation_id="op_drop",
                column_ids=("col_secret",),
            ),
            DeduplicateOperation(operation_id="op_dedupe"),
        )
    )

    result = DuckDBEngine(Settings(environment="test")).preview(
        DatasetSource(uri=str(parquet_path)),
        _schema(),
        pipeline,
        limit=100,
    )

    assert result.column_names == ["age", "city"]
    assert result.to_pydict() == {"age": [25], "city": ["Unknown"]}

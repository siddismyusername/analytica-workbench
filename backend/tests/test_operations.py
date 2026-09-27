import pytest
from fastapi.testclient import TestClient

from analytica_api.domain.datasets import DatasetColumn, DatasetSchema
from analytica_api.execution.duckdb_engine import PipelineCompilationError, PipelineCompiler
from analytica_api.main import create_app
from analytica_api.operations.models import DropColumnsOperation, PipelineSpec


@pytest.fixture
def schema() -> DatasetSchema:
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
        )
    )


def test_operation_catalog_is_exposed() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/operations")
    assert response.status_code == 200
    assert {item["type"] for item in response.json()} == {
        "filter",
        "drop_columns",
        "fill_null",
        "deduplicate",
    }


def test_pipeline_rejects_unknown_column(schema: DatasetSchema) -> None:
    pipeline = PipelineSpec(
        operations=(
            DropColumnsOperation(operation_id="op_1", column_ids=("missing",)),
        )
    )
    with pytest.raises(PipelineCompilationError, match="unknown column_id"):
        PipelineCompiler(schema).validate(pipeline)


def test_pipeline_cannot_drop_every_column(schema: DatasetSchema) -> None:
    pipeline = PipelineSpec(
        operations=(
            DropColumnsOperation(
                operation_id="op_1",
                column_ids=("col_age", "col_city"),
            ),
        )
    )
    with pytest.raises(PipelineCompilationError, match="cannot drop every column"):
        PipelineCompiler(schema).validate(pipeline)

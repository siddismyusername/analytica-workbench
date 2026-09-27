from dataclasses import dataclass
from typing import Any

import duckdb
import pyarrow as pa

from analytica_api.config import Settings
from analytica_api.domain.datasets import DatasetSchema, DatasetSource
from analytica_api.operations.models import (
    DeduplicateOperation,
    DropColumnsOperation,
    FillNullOperation,
    FilterOperation,
    PipelineSpec,
)


class PipelineCompilationError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: tuple[Any, ...]
    active_column_ids: tuple[str, ...]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class PipelineCompiler:
    """Compile the versioned operation DSL into parameterized DuckDB SQL."""

    _FILTER_SQL = {
        "eq": "=",
        "neq": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }

    def __init__(self, schema: DatasetSchema):
        self.schema = schema
        self.columns = schema.by_id()

    def _require_active(self, column_id: str, active: list[str]) -> str:
        if column_id not in self.columns:
            raise PipelineCompilationError(f"unknown column_id: {column_id}")
        if column_id not in active:
            raise PipelineCompilationError(f"column is not active: {column_id}")
        return self.columns[column_id].physical_name

    def validate(self, pipeline: PipelineSpec) -> tuple[str, ...]:
        active = [column.column_id for column in self.schema.columns]
        for operation in pipeline.operations:
            if isinstance(operation, (FilterOperation, FillNullOperation)):
                self._require_active(operation.column_id, active)
            elif isinstance(operation, DropColumnsOperation):
                for column_id in operation.column_ids:
                    self._require_active(column_id, active)
                remaining = [item for item in active if item not in operation.column_ids]
                if not remaining:
                    raise PipelineCompilationError("a pipeline cannot drop every column")
                active = remaining
            elif isinstance(operation, DeduplicateOperation):
                continue
        return tuple(active)

    def compile(
        self,
        source: DatasetSource,
        pipeline: PipelineSpec,
        *,
        selected_column_ids: tuple[str, ...] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> CompiledQuery:
        if limit is not None and limit < 1:
            raise PipelineCompilationError("limit must be greater than zero")
        if offset < 0:
            raise PipelineCompilationError("offset cannot be negative")

        active = list(self.validate(pipeline))
        parameters: list[Any] = [source.uri]
        ctes = ["source_data AS (SELECT * FROM read_parquet(?))"]
        current_relation = "source_data"

        for index, operation in enumerate(pipeline.operations, start=1):
            step_name = f"step_{index}"
            if isinstance(operation, FilterOperation):
                physical_name = self.columns[operation.column_id].physical_name
                column_sql = quote_identifier(physical_name)
                if operation.operator == "is_null":
                    predicate = f"{column_sql} IS NULL"
                elif operation.operator == "not_null":
                    predicate = f"{column_sql} IS NOT NULL"
                else:
                    predicate = f"{column_sql} {self._FILTER_SQL[operation.operator]} ?"
                    parameters.append(operation.value)
                step_sql = f"SELECT * FROM {current_relation} WHERE {predicate}"
            elif isinstance(operation, FillNullOperation):
                physical_name = self.columns[operation.column_id].physical_name
                column_sql = quote_identifier(physical_name)
                step_sql = (
                    f"SELECT * REPLACE (COALESCE({column_sql}, ?) AS {column_sql}) "
                    f"FROM {current_relation}"
                )
                parameters.append(operation.value)
            elif isinstance(operation, DropColumnsOperation):
                excluded = ", ".join(
                    quote_identifier(self.columns[column_id].physical_name)
                    for column_id in operation.column_ids
                )
                step_sql = f"SELECT * EXCLUDE ({excluded}) FROM {current_relation}"
            elif isinstance(operation, DeduplicateOperation):
                step_sql = f"SELECT DISTINCT * FROM {current_relation}"
            else:  # pragma: no cover - the discriminated union prevents this state.
                raise PipelineCompilationError(f"unsupported operation: {operation.type}")

            ctes.append(f"{step_name} AS ({step_sql})")
            current_relation = step_name

        if selected_column_ids is not None:
            if not selected_column_ids:
                raise PipelineCompilationError("selected_column_ids cannot be empty")
            selected_sql: list[str] = []
            for column_id in selected_column_ids:
                physical_name = self._require_active(column_id, active)
                selected_sql.append(quote_identifier(physical_name))
            final_select = f"SELECT {', '.join(selected_sql)} FROM {current_relation}"
            active = list(selected_column_ids)
        else:
            final_select = f"SELECT * FROM {current_relation}"

        if limit is not None:
            final_select += " LIMIT ? OFFSET ?"
            parameters.extend([limit, offset])

        return CompiledQuery(
            sql=f"WITH {', '.join(ctes)} {final_select}",
            parameters=tuple(parameters),
            active_column_ids=tuple(active),
        )


class DuckDBEngine:
    """Bounded analytical execution for canonical Parquet datasets."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def execute_arrow(self, query: CompiledQuery) -> pa.Table:
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(f"SET threads TO {int(self.settings.duckdb_threads)}")
            return connection.execute(query.sql, query.parameters).fetch_arrow_table()
        finally:
            connection.close()

    def preview(
        self,
        source: DatasetSource,
        schema: DatasetSchema,
        pipeline: PipelineSpec,
        *,
        limit: int,
        offset: int = 0,
        selected_column_ids: tuple[str, ...] | None = None,
    ) -> pa.Table:
        compiled = PipelineCompiler(schema).compile(
            source,
            pipeline,
            selected_column_ids=selected_column_ids,
            limit=limit,
            offset=offset,
        )
        return self.execute_arrow(compiled)

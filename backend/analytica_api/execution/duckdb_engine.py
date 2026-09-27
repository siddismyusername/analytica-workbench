from dataclasses import dataclass
from typing import Any

import duckdb
import pyarrow as pa

from analytica_api.config import Settings
from analytica_api.domain.datasets import DatasetColumn, DatasetSchema, DatasetSource
from analytica_api.operations.models import (
    CastColumnOperation,
    DeduplicateOperation,
    DropColumnsOperation,
    FillNullOperation,
    FilterOperation,
    PipelineSpec,
    RenameColumnOperation,
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


_CAST_SQL = {
    "boolean": "BOOLEAN",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "string": "VARCHAR",
    "date": "DATE",
    "datetime": "TIMESTAMP",
}

_STORAGE_TYPES = {
    "boolean": "BOOLEAN",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "string": "VARCHAR",
    "date": "DATE",
    "datetime": "TIMESTAMP",
}


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

    def _require_active(self, column_id: str, active: list[str]) -> None:
        if column_id not in self.columns:
            raise PipelineCompilationError(f"unknown column_id: {column_id}")
        if column_id not in active:
            raise PipelineCompilationError(f"column is not active: {column_id}")

    def _state(self) -> tuple[list[str], dict[str, str]]:
        active = [column.column_id for column in self.schema.columns]
        names = {column.column_id: column.physical_name for column in self.schema.columns}
        return active, names

    def _advance_state(
        self,
        operation: object,
        active: list[str],
        names: dict[str, str],
    ) -> None:
        if isinstance(operation, (FilterOperation, FillNullOperation, CastColumnOperation)):
            self._require_active(operation.column_id, active)
        elif isinstance(operation, RenameColumnOperation):
            self._require_active(operation.column_id, active)
            if operation.new_name in {
                names[column_id] for column_id in active if column_id != operation.column_id
            }:
                raise PipelineCompilationError(f"column name already exists: {operation.new_name}")
            names[operation.column_id] = operation.new_name
        elif isinstance(operation, DropColumnsOperation):
            for column_id in operation.column_ids:
                self._require_active(column_id, active)
            remaining = [item for item in active if item not in operation.column_ids]
            if not remaining:
                raise PipelineCompilationError("a pipeline cannot drop every column")
            active[:] = remaining
        elif isinstance(operation, DeduplicateOperation):
            return

    def validate(self, pipeline: PipelineSpec) -> tuple[str, ...]:
        active, names = self._state()
        for operation in pipeline.operations:
            self._advance_state(operation, active, names)
        return tuple(active)

    def evolve_schema(self, pipeline: PipelineSpec) -> DatasetSchema:
        active, names = self._state()
        target_types = {column.column_id: column.data_type for column in self.schema.columns}
        target_storage = {column.column_id: column.storage_type for column in self.schema.columns}
        for operation in pipeline.operations:
            self._advance_state(operation, active, names)
            if isinstance(operation, CastColumnOperation):
                target_types[operation.column_id] = operation.target_type
                target_storage[operation.column_id] = _STORAGE_TYPES[operation.target_type]

        columns: list[DatasetColumn] = []
        for column in self.schema.columns:
            if column.column_id not in active:
                continue
            new_name = names[column.column_id]
            columns.append(
                column.model_copy(
                    update={
                        "physical_name": new_name,
                        "display_name": (
                            new_name if new_name != column.physical_name else column.display_name
                        ),
                        "data_type": target_types[column.column_id],
                        "storage_type": target_storage[column.column_id],
                    }
                )
            )
        return DatasetSchema(columns=tuple(columns))

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

        active, names = self._state()
        parameters: list[Any] = [source.uri]
        ctes = ["source_data AS (SELECT * FROM read_parquet(?))"]
        current_relation = "source_data"

        for index, operation in enumerate(pipeline.operations, start=1):
            step_name = f"step_{index}"
            if isinstance(operation, FilterOperation):
                self._require_active(operation.column_id, active)
                column_sql = quote_identifier(names[operation.column_id])
                if operation.operator == "is_null":
                    predicate = f"{column_sql} IS NULL"
                elif operation.operator == "not_null":
                    predicate = f"{column_sql} IS NOT NULL"
                else:
                    predicate = f"{column_sql} {self._FILTER_SQL[operation.operator]} ?"
                    parameters.append(operation.value)
                step_sql = f"SELECT * FROM {current_relation} WHERE {predicate}"
            elif isinstance(operation, FillNullOperation):
                self._require_active(operation.column_id, active)
                column_sql = quote_identifier(names[operation.column_id])
                step_sql = (
                    f"SELECT * REPLACE (COALESCE({column_sql}, ?) AS {column_sql}) "
                    f"FROM {current_relation}"
                )
                parameters.append(operation.value)
            elif isinstance(operation, CastColumnOperation):
                self._require_active(operation.column_id, active)
                column_sql = quote_identifier(names[operation.column_id])
                target_sql = _CAST_SQL[operation.target_type]
                step_sql = (
                    f"SELECT * REPLACE (CAST({column_sql} AS {target_sql}) AS {column_sql}) "
                    f"FROM {current_relation}"
                )
            elif isinstance(operation, RenameColumnOperation):
                self._require_active(operation.column_id, active)
                if operation.new_name in {
                    names[column_id] for column_id in active if column_id != operation.column_id
                }:
                    raise PipelineCompilationError(
                        f"column name already exists: {operation.new_name}"
                    )
                projection = []
                for column_id in active:
                    source_name = names[column_id]
                    if column_id == operation.column_id:
                        source_sql = quote_identifier(source_name)
                        target_sql = quote_identifier(operation.new_name)
                        projection.append(f"{source_sql} AS {target_sql}")
                    else:
                        projection.append(quote_identifier(source_name))
                step_sql = f"SELECT {', '.join(projection)} FROM {current_relation}"
                names[operation.column_id] = operation.new_name
            elif isinstance(operation, DropColumnsOperation):
                for column_id in operation.column_ids:
                    self._require_active(column_id, active)
                remaining = [item for item in active if item not in operation.column_ids]
                if not remaining:
                    raise PipelineCompilationError("a pipeline cannot drop every column")
                selected = ", ".join(quote_identifier(names[column_id]) for column_id in remaining)
                step_sql = f"SELECT {selected} FROM {current_relation}"
                active = remaining
            elif isinstance(operation, DeduplicateOperation):
                step_sql = f"SELECT DISTINCT * FROM {current_relation}"
            else:  # pragma: no cover
                raise PipelineCompilationError(f"unsupported operation: {operation.type}")

            ctes.append(f"{step_name} AS ({step_sql})")
            current_relation = step_name

        if selected_column_ids is not None:
            if not selected_column_ids:
                raise PipelineCompilationError("selected_column_ids cannot be empty")
            selected_sql: list[str] = []
            for column_id in selected_column_ids:
                self._require_active(column_id, active)
                selected_sql.append(quote_identifier(names[column_id]))
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
            return connection.execute(query.sql, query.parameters).to_arrow_table()
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

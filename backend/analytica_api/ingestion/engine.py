from pathlib import Path
from uuid import uuid4

import duckdb

from analytica_api.config import Settings
from analytica_api.domain.datasets import DatasetColumn, DatasetSchema, DataType
from analytica_api.ingestion.models import IngestionManifest, SourceFormat


class IngestionError(RuntimeError):
    pass


def _sql_string_literal(value: str) -> str:
    """Quote an internal filesystem path as a DuckDB SQL string literal."""

    return "'" + value.replace("'", "''") + "'"


def _logical_type(storage_type: str) -> DataType:
    value = storage_type.upper()
    if value == "BOOLEAN":
        return "boolean"
    if "INT" in value:
        return "integer"
    if value.startswith(("DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return "float"
    if value == "DATE":
        return "date"
    if value.startswith("TIMESTAMP"):
        return "datetime"
    if value.startswith("ENUM"):
        return "categorical"
    if value.startswith(("VARCHAR", "CHAR", "TEXT")):
        return "string"
    return "unknown"


class IngestionEngine:
    """Convert trusted worker-local inputs into immutable canonical Parquet files."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def ingest_local(
        self,
        source_path: Path,
        target_path: Path,
        *,
        source_format: SourceFormat,
    ) -> IngestionManifest:
        source_path = source_path.resolve()
        target_path = target_path.resolve()

        if not source_path.is_file():
            raise IngestionError(f"source file does not exist: {source_path}")
        if target_path.exists():
            raise IngestionError(f"canonical target already exists: {target_path}")
        if source_path == target_path:
            raise IngestionError("source and canonical target must be different files")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(database=":memory:")

        try:
            connection.execute(f"SET threads TO {int(self.settings.duckdb_threads)}")

            if source_format == "csv":
                connection.execute(
                    "CREATE TEMP TABLE ingested AS "
                    "SELECT * FROM read_csv(?, strict_mode = true)",
                    [str(source_path)],
                )
            elif source_format == "parquet":
                connection.execute(
                    "CREATE TEMP TABLE ingested AS SELECT * FROM read_parquet(?)",
                    [str(source_path)],
                )
            else:
                raise IngestionError(f"unsupported source format: {source_format}")

            row_count = int(connection.execute("SELECT COUNT(*) FROM ingested").fetchone()[0])
            description = connection.execute("DESCRIBE ingested").fetchall()

            target_sql = _sql_string_literal(str(target_path))
            connection.execute(f"COPY ingested TO {target_sql} (FORMAT parquet)")

            columns = tuple(
                DatasetColumn(
                    column_id=f"col_{uuid4().hex}",
                    physical_name=str(row[0]),
                    display_name=str(row[0]),
                    data_type=_logical_type(str(row[1])),
                    storage_type=str(row[1]),
                    nullable=str(row[2]).upper() != "NO",
                )
                for row in description
            )

            return IngestionManifest(
                source_format=source_format,
                row_count=row_count,
                byte_size=target_path.stat().st_size,
                schema=DatasetSchema(columns=columns),
            )
        except duckdb.Error as exc:
            if target_path.exists():
                target_path.unlink()
            raise IngestionError(f"dataset ingestion failed: {exc}") from exc
        except Exception:
            if target_path.exists():
                target_path.unlink()
            raise
        finally:
            connection.close()

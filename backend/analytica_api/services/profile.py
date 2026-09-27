from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import duckdb

from analytica_api.domain.datasets import DatasetSchema
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    display_name: str
    data_type: str
    storage_type: str | None
    nullable: bool
    null_count: int
    null_percentage: float
    distinct_count: int


@dataclass(frozen=True)
class ProfileWarning:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class DatasetProfile:
    version_id: UUID
    dataset_id: UUID
    dataset_name: str
    version_number: int
    row_count: int
    column_count: int
    byte_size: int
    missing_cells: int
    missing_percentage: float
    duplicate_rows: int
    duplicate_percentage: float
    columns: tuple[ColumnProfile, ...]
    warnings: tuple[ProfileWarning, ...]


def _quoted_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


class DatasetProfileService:
    """Profile an immutable canonical dataset without creating a second data copy."""

    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store

    def profile(self, version_id: UUID) -> DatasetProfile:
        version = self.control_plane.get_version(version_id)
        dataset = self.control_plane.get_dataset(version.dataset_id)
        artifact = self.control_plane.get_artifact_for_version_kind(
            version_id, "canonical_dataset"
        )
        schema = DatasetSchema.model_validate(version.schema_snapshot)
        object_ref = StorageObjectRef(
            key=artifact.storage_key,
            byte_size=artifact.byte_size,
            content_type=artifact.content_type,
            checksum_sha256=artifact.checksum_sha256,
        )

        with TemporaryDirectory(prefix="analytica-profile-") as directory:
            path = self.artifact_store.materialize(
                object_ref, Path(directory) / "dataset.parquet"
            )
            connection = duckdb.connect(database=":memory:")
            try:
                row_count, column_profiles = self._column_metrics(
                    connection, path, schema
                )
                duplicate_rows = self._duplicate_rows(connection, path, schema)
            finally:
                connection.close()

        missing_cells = sum(column.null_count for column in column_profiles)
        cell_count = row_count * len(column_profiles)
        warnings = self._warnings(
            row_count=row_count,
            duplicate_rows=duplicate_rows,
            columns=column_profiles,
        )
        return DatasetProfile(
            version_id=version.id,
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            version_number=version.version_number,
            row_count=row_count,
            column_count=len(column_profiles),
            byte_size=version.byte_size,
            missing_cells=missing_cells,
            missing_percentage=_percentage(missing_cells, cell_count),
            duplicate_rows=duplicate_rows,
            duplicate_percentage=_percentage(duplicate_rows, row_count),
            columns=column_profiles,
            warnings=warnings,
        )

    def _column_metrics(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: Path,
        schema: DatasetSchema,
    ) -> tuple[int, tuple[ColumnProfile, ...]]:
        expressions = ["COUNT(*) AS _row_count"]
        for index, column in enumerate(schema.columns):
            identifier = _quoted_identifier(column.physical_name)
            expressions.extend(
                [
                    f"COUNT(*) - COUNT({identifier}) AS _null_{index}",
                    f"APPROX_COUNT_DISTINCT({identifier}) AS _distinct_{index}",
                ]
            )
        query = f"SELECT {', '.join(expressions)} FROM read_parquet(?)"
        values = connection.execute(query, [str(path)]).fetchone()
        if values is None:
            raise RuntimeError("profiling query returned no result")

        row_count = int(values[0])
        profiles: list[ColumnProfile] = []
        for index, column in enumerate(schema.columns):
            null_count = int(values[1 + index * 2])
            distinct_count = int(values[2 + index * 2])
            profiles.append(
                ColumnProfile(
                    name=column.physical_name,
                    display_name=column.display_name,
                    data_type=column.data_type,
                    storage_type=column.storage_type,
                    nullable=column.nullable,
                    null_count=null_count,
                    null_percentage=_percentage(null_count, row_count),
                    distinct_count=distinct_count,
                )
            )
        return row_count, tuple(profiles)

    def _duplicate_rows(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: Path,
        schema: DatasetSchema,
    ) -> int:
        identifiers = ", ".join(
            _quoted_identifier(column.physical_name) for column in schema.columns
        )
        query = (
            "SELECT COALESCE(SUM(_row_count - 1), 0) FROM ("
            f"SELECT {identifiers}, COUNT(*) AS _row_count FROM read_parquet(?) "
            f"GROUP BY {identifiers} HAVING COUNT(*) > 1)"
        )
        value = connection.execute(query, [str(path)]).fetchone()
        return int(value[0]) if value is not None else 0

    def _warnings(
        self,
        *,
        row_count: int,
        duplicate_rows: int,
        columns: tuple[ColumnProfile, ...],
    ) -> tuple[ProfileWarning, ...]:
        warnings: list[ProfileWarning] = []
        columns_with_missing = [column for column in columns if column.null_count > 0]
        if columns_with_missing:
            warnings.append(
                ProfileWarning(
                    code="missing_values",
                    severity="warning",
                    message=(
                        f"{len(columns_with_missing)} column(s) contain missing values."
                    ),
                )
            )
        if duplicate_rows > 0:
            warnings.append(
                ProfileWarning(
                    code="duplicate_rows",
                    severity="warning",
                    message=f"{duplicate_rows} duplicate row(s) were detected.",
                )
            )
        constant_columns = [
            column
            for column in columns
            if row_count > 0
            and column.distinct_count <= 1
            and column.null_count < row_count
        ]
        if constant_columns:
            warnings.append(
                ProfileWarning(
                    code="constant_columns",
                    severity="info",
                    message=f"{len(constant_columns)} column(s) have one observed value.",
                )
            )
        return tuple(warnings)

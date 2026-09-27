from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import duckdb

from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.storage.contracts import ArtifactStore, StorageObjectRef


@dataclass(frozen=True)
class DatasetPreview:
    version_id: UUID
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    offset: int
    limit: int


class DatasetPreviewService:
    def __init__(
        self,
        *,
        control_plane: ControlPlaneService,
        artifact_store: ArtifactStore,
    ):
        self.control_plane = control_plane
        self.artifact_store = artifact_store

    def preview(self, version_id: UUID, *, offset: int = 0, limit: int = 50) -> DatasetPreview:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        artifact = self.control_plane.get_artifact_for_version_kind(
            version_id, "canonical_dataset"
        )
        object_ref = StorageObjectRef(
            key=artifact.storage_key,
            byte_size=artifact.byte_size,
            content_type=artifact.content_type,
            checksum_sha256=artifact.checksum_sha256,
        )
        with TemporaryDirectory(prefix="analytica-preview-") as directory:
            path = self.artifact_store.materialize(
                object_ref, Path(directory) / "dataset.parquet"
            )
            connection = duckdb.connect(database=":memory:")
            try:
                cursor = connection.execute(
                    "SELECT * FROM read_parquet(?) LIMIT ? OFFSET ?",
                    [str(path), limit, offset],
                )
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(tuple(row) for row in cursor.fetchall())
            finally:
                connection.close()

        return DatasetPreview(
            version_id=version_id,
            columns=columns,
            rows=rows,
            offset=offset,
            limit=limit,
        )

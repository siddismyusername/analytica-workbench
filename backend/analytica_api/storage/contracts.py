from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class StorageError(RuntimeError):
    pass


class StorageObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ArtifactStore(Protocol):
    def put_file(
        self,
        source_path: Path,
        *,
        key: str,
        content_type: str,
    ) -> StorageObjectRef: ...

    def stat(self, key: str) -> StorageObjectRef: ...

    def materialize(self, object_ref: StorageObjectRef, target_path: Path) -> Path: ...

    def delete(self, object_ref: StorageObjectRef) -> None: ...

    def exists(self, object_ref: StorageObjectRef) -> bool: ...

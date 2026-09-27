import hashlib
import shutil
from pathlib import Path, PurePosixPath

from analytica_api.storage.contracts import StorageObjectRef


class StorageError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalArtifactStore:
    """Immutable local filesystem store for development and tests."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, key: str) -> Path:
        posix_path = PurePosixPath(key)
        if not key or posix_path.is_absolute() or ".." in posix_path.parts:
            raise StorageError("storage key must be a non-empty relative path")
        target = (self.root / Path(*posix_path.parts)).resolve()
        if target != self.root and self.root not in target.parents:
            raise StorageError("storage key escapes the configured artifact root")
        return target

    def put_file(
        self,
        source_path: Path,
        *,
        key: str,
        content_type: str,
    ) -> StorageObjectRef:
        source = source_path.resolve()
        if not source.is_file():
            raise StorageError(f"source artifact does not exist: {source}")

        target = self._resolve_key(key)
        if target.exists():
            raise StorageError(f"artifact key already exists: {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

        return StorageObjectRef(
            key=key,
            byte_size=target.stat().st_size,
            content_type=content_type,
            checksum_sha256=_sha256(target),
        )

    def materialize(self, object_ref: StorageObjectRef, target_path: Path) -> Path:
        source = self._resolve_key(object_ref.key)
        if not source.is_file():
            raise StorageError(f"artifact is missing: {object_ref.key}")

        target = target_path.resolve()
        if target.exists():
            raise StorageError(f"materialization target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    def delete(self, object_ref: StorageObjectRef) -> None:
        path = self._resolve_key(object_ref.key)
        if path.exists():
            path.unlink()

    def exists(self, object_ref: StorageObjectRef) -> bool:
        return self._resolve_key(object_ref.key).is_file()

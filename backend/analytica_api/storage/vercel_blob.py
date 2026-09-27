from pathlib import Path

from vercel.blob import delete, download_file, head, upload_file

from analytica_api.storage.contracts import StorageError, StorageObjectRef


class VercelBlobArtifactStore:
    """Private Vercel Blob adapter used by production ingestion workers."""

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
        try:
            result = upload_file(
                source,
                key,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
                overwrite=False,
                multipart=True,
            )
            return self.stat(result.pathname)
        except Exception as exc:
            raise StorageError(f"Vercel Blob upload failed for {key}: {exc}") from exc

    def stat(self, key: str) -> StorageObjectRef:
        try:
            result = head(key)
            return StorageObjectRef(
                key=result.pathname,
                byte_size=result.size,
                content_type=result.content_type or "application/octet-stream",
            )
        except Exception as exc:
            raise StorageError(f"Vercel Blob object is unavailable: {key}: {exc}") from exc

    def materialize(self, object_ref: StorageObjectRef, target_path: Path) -> Path:
        target = target_path.resolve()
        if target.exists():
            raise StorageError(f"materialization target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            download_file(
                object_ref.key,
                target,
                access="private",
                overwrite=False,
                create_parents=True,
            )
        except Exception as exc:
            raise StorageError(
                f"Vercel Blob download failed for {object_ref.key}: {exc}"
            ) from exc

        actual_size = target.stat().st_size
        if actual_size != object_ref.byte_size:
            target.unlink(missing_ok=True)
            raise StorageError(
                f"materialized artifact size mismatch: expected {object_ref.byte_size}, "
                f"got {actual_size}"
            )
        return target

    def delete(self, object_ref: StorageObjectRef) -> None:
        try:
            delete(object_ref.key)
        except Exception as exc:
            raise StorageError(
                f"Vercel Blob delete failed for {object_ref.key}: {exc}"
            ) from exc

    def exists(self, object_ref: StorageObjectRef) -> bool:
        try:
            self.stat(object_ref.key)
        except StorageError:
            return False
        return True

from pathlib import Path

from vercel.blob import BlobClient, BlobError, BlobNotFoundError

from analytica_api.storage.contracts import StorageError, StorageObjectRef


class VercelBlobArtifactStore:
    """Private Vercel Blob adapter using the public Python SDK."""

    def __init__(self, client: BlobClient | None = None):
        self.client = client or BlobClient()

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
            result = self.client.upload_file(
                str(source),
                key,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
                overwrite=False,
                multipart=True,
            )
        except BlobError as exc:
            raise StorageError(f"failed to upload artifact {key}: {exc}") from exc
        return StorageObjectRef(
            key=result.pathname,
            byte_size=source.stat().st_size,
            content_type=result.content_type or content_type,
        )

    def stat(self, key: str) -> StorageObjectRef:
        try:
            result = self.client.head(key)
        except BlobNotFoundError as exc:
            raise StorageError(f"artifact is missing: {key}") from exc
        except BlobError as exc:
            raise StorageError(f"failed to inspect artifact {key}: {exc}") from exc
        return StorageObjectRef(
            key=result.pathname,
            byte_size=result.size,
            content_type=result.content_type or "application/octet-stream",
        )

    def materialize(self, object_ref: StorageObjectRef, target_path: Path) -> Path:
        target = target_path.resolve()
        if target.exists():
            raise StorageError(f"materialization target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(
                object_ref.key,
                str(target),
                access="private",
                overwrite=False,
                create_parents=True,
            )
        except BlobNotFoundError as exc:
            target.unlink(missing_ok=True)
            raise StorageError(f"artifact is missing: {object_ref.key}") from exc
        except BlobError as exc:
            target.unlink(missing_ok=True)
            raise StorageError(f"failed to download artifact {object_ref.key}: {exc}") from exc

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
            self.client.delete(object_ref.key)
        except BlobError as exc:
            raise StorageError(f"failed to delete artifact {object_ref.key}: {exc}") from exc

    def exists(self, object_ref: StorageObjectRef) -> bool:
        try:
            self.client.head(object_ref.key)
        except BlobNotFoundError:
            return False
        except BlobError as exc:
            raise StorageError(f"failed to inspect artifact {object_ref.key}: {exc}") from exc
        return True

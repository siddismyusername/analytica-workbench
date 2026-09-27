from pathlib import Path

from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError

from analytica_api.storage.contracts import StorageObjectRef


class VercelBlobArtifactStore:
    """Private Vercel Blob adapter used by production ingestion workers."""

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
            raise FileNotFoundError(f"source artifact does not exist: {source}")

        result = self.client.put(
            key,
            source.read_bytes(),
            access="private",
            content_type=content_type,
            add_random_suffix=False,
            overwrite=False,
            multipart=True,
        )
        return StorageObjectRef(
            key=result.pathname,
            byte_size=source.stat().st_size,
            content_type=result.content_type or content_type,
        )

    def materialize(self, object_ref: StorageObjectRef, target_path: Path) -> Path:
        result = self.client.get(object_ref.key, access="private")
        if result is None or result.status_code != 200 or result.stream is None:
            raise FileNotFoundError(f"artifact is missing: {object_ref.key}")

        target = target_path.resolve()
        if target.exists():
            raise FileExistsError(f"materialization target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            for chunk in result.stream:
                handle.write(chunk)

        actual_size = target.stat().st_size
        if actual_size != object_ref.byte_size:
            target.unlink(missing_ok=True)
            raise ValueError(
                f"materialized artifact size mismatch: expected {object_ref.byte_size}, "
                f"got {actual_size}"
            )
        return target

    def delete(self, object_ref: StorageObjectRef) -> None:
        self.client.delete(object_ref.key)

    def exists(self, object_ref: StorageObjectRef) -> bool:
        try:
            self.client.head(object_ref.key)
        except BlobNotFoundError:
            return False
        return True

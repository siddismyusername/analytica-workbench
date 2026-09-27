from pathlib import Path
from types import SimpleNamespace

from analytica_api.storage.vercel_blob import VercelBlobArtifactStore


class FakeBlobClient:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.upload_calls: list[dict[str, object]] = []

    def upload_file(self, local_path: str, path: str, **kwargs):
        data = Path(local_path).read_bytes()
        content_type = str(kwargs["content_type"])
        self.objects[path] = (data, content_type)
        self.upload_calls.append({"path": path, **kwargs})
        return SimpleNamespace(pathname=path, content_type=content_type)

    def head(self, path: str):
        data, content_type = self.objects[path]
        return SimpleNamespace(pathname=path, size=len(data), content_type=content_type)

    def download_file(self, path: str, local_path: str, **kwargs):
        del kwargs
        data, _ = self.objects[path]
        Path(local_path).write_bytes(data)
        return local_path

    def delete(self, path: str):
        self.objects.pop(path, None)


def test_vercel_blob_adapter_uses_file_streaming_sdk_methods(tmp_path: Path) -> None:
    client = FakeBlobClient()
    store = VercelBlobArtifactStore(client=client)  # type: ignore[arg-type]
    source = tmp_path / "data.parquet"
    source.write_bytes(b"canonical-parquet")

    ref = store.put_file(
        source,
        key="datasets/one/data.parquet",
        content_type="application/vnd.apache.parquet",
    )
    assert client.upload_calls[0]["multipart"] is True
    assert client.upload_calls[0]["overwrite"] is False
    assert store.stat(ref.key).byte_size == len(b"canonical-parquet")

    target = store.materialize(ref, tmp_path / "download" / "data.parquet")
    assert target.read_bytes() == b"canonical-parquet"
    assert store.exists(ref)

from pathlib import Path

import pytest

from analytica_api.domain.control_plane import JobStatus
from analytica_api.domain.datasets import DatasetColumn, DatasetSchema
from analytica_api.ingestion.models import IngestionManifest
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.storage.contracts import StorageObjectRef
from analytica_api.storage.local import LocalArtifactStore, StorageError


def _service(tmp_path: Path) -> tuple[ControlPlaneService, Database]:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'control-plane.db'}")
    Base.metadata.create_all(database.engine)
    service = ControlPlaneService(
        lambda: SqlAlchemyUnitOfWork(database.session_factory)
    )
    return service, database


def _manifest(byte_size: int = 128) -> IngestionManifest:
    return IngestionManifest(
        source_format="csv",
        row_count=2,
        byte_size=byte_size,
        schema=DatasetSchema(
            columns=(
                DatasetColumn(
                    column_id="col_age",
                    physical_name="age",
                    display_name="age",
                    data_type="integer",
                    storage_type="BIGINT",
                    nullable=False,
                ),
            )
        ),
    )


def _object_ref(byte_size: int = 128) -> StorageObjectRef:
    return StorageObjectRef(
        key="datasets/dataset/version/data.parquet",
        byte_size=byte_size,
        content_type="application/vnd.apache.parquet",
        checksum_sha256="a" * 64,
    )


def test_registering_ingestion_creates_immutable_numbered_versions(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    try:
        dataset = service.create_dataset("  Customers  ")
        first = service.register_ingested_version(
            dataset_id=dataset.id,
            manifest=_manifest(),
            object_ref=_object_ref(),
        )
        second = service.register_ingested_version(
            dataset_id=dataset.id,
            manifest=_manifest(),
            object_ref=StorageObjectRef(
                key="datasets/dataset/version-2/data.parquet",
                byte_size=128,
                content_type="application/vnd.apache.parquet",
                checksum_sha256="b" * 64,
            ),
            parent_version_id=first.version.id,
        )

        assert dataset.name == "Customers"
        assert first.version.version_number == 1
        assert second.version.version_number == 2
        assert second.version.parent_version_id == first.version.id
        assert first.artifact.dataset_version_id == first.version.id
        assert first.artifact.kind == "canonical_dataset"
    finally:
        database.dispose()


def test_registration_rejects_manifest_artifact_size_mismatch(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    try:
        dataset = service.create_dataset("Customers")
        with pytest.raises(ControlPlaneError, match="size does not match"):
            service.register_ingested_version(
                dataset_id=dataset.id,
                manifest=_manifest(byte_size=10),
                object_ref=_object_ref(byte_size=11),
            )
    finally:
        database.dispose()


def test_jobs_are_idempotent_and_enforce_state_transitions(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    try:
        first = service.create_job(kind="ingest", idempotency_key="upload:abc")
        repeated = service.create_job(kind="ingest", idempotency_key="upload:abc")
        assert first.id == repeated.id
        assert first.status == JobStatus.QUEUED

        running = service.transition_job(first.id, JobStatus.RUNNING)
        assert running.status == JobStatus.RUNNING
        assert running.attempt_count == 1
        assert running.started_at is not None

        succeeded = service.transition_job(first.id, JobStatus.SUCCEEDED)
        assert succeeded.completed_at is not None
        with pytest.raises(ControlPlaneError, match="invalid job transition"):
            service.transition_job(first.id, JobStatus.RUNNING)
    finally:
        database.dispose()


def test_local_artifact_store_is_immutable_and_blocks_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"parquet-bytes")
    store = LocalArtifactStore(tmp_path / "artifacts")

    object_ref = store.put_file(
        source,
        key="datasets/one/version-1/data.parquet",
        content_type="application/vnd.apache.parquet",
    )
    assert store.exists(object_ref)
    assert object_ref.byte_size == len(b"parquet-bytes")
    assert object_ref.checksum_sha256 is not None

    with pytest.raises(StorageError, match="already exists"):
        store.put_file(
            source,
            key=object_ref.key,
            content_type=object_ref.content_type,
        )
    with pytest.raises(StorageError, match="relative path"):
        store.put_file(source, key="../escape", content_type="application/octet-stream")

    materialized = store.materialize(object_ref, tmp_path / "copy" / "data.parquet")
    assert materialized.read_bytes() == b"parquet-bytes"

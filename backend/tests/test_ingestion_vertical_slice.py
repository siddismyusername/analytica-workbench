import asyncio
from pathlib import Path

import pytest

from analytica_api.config import Settings
from analytica_api.domain.control_plane import JobStatus
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.services.control_plane import ControlPlaneError, ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.local import LocalArtifactStore


def _stack(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'vertical.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    control_plane = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    worker = IngestionWorker(settings=settings, control_plane=control_plane, store=store)
    service = DatasetIngestionService(
        settings=settings,
        control_plane=control_plane,
        artifact_store=store,
        job_queue=InlineJobQueue(worker.run),
    )
    preview = DatasetPreviewService(control_plane=control_plane, artifact_store=store)
    return database, store, control_plane, service, preview


def test_direct_upload_becomes_durable_job_parquet_version_and_preview(tmp_path: Path) -> None:
    database, store, control_plane, service, preview = _stack(tmp_path)
    upload = tmp_path / "customers.csv"
    upload.write_text("name,age\nAda,36\nGrace,40\n", encoding="utf-8")
    source_ref = store.put_file(
        upload,
        key="raw/session-1/customers.csv",
        content_type="text/csv",
    )

    try:
        first = asyncio.run(
            service.submit_uploaded_dataset(
                name="Customers",
                source_key=source_ref.key,
                source_format="csv",
                idempotency_key="upload:customers:1",
            )
        )
        repeated = asyncio.run(
            service.submit_uploaded_dataset(
                name="Customers",
                source_key=source_ref.key,
                source_format="csv",
                idempotency_key="upload:customers:1",
            )
        )
        job = control_plane.get_job(first.job.id)
        assert job.status == JobStatus.SUCCEEDED
        assert job.output_version_id is not None
        assert repeated.job.id == first.job.id
        assert repeated.dataset_id == first.dataset_id

        dataset_preview = preview.preview(job.output_version_id, limit=10)
        assert dataset_preview.columns == ("name", "age")
        assert dataset_preview.rows == (("Ada", 36), ("Grace", 40))
    finally:
        database.dispose()


def test_idempotency_key_cannot_be_reused_for_different_upload(tmp_path: Path) -> None:
    database, store, _, service, _ = _stack(tmp_path)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("value\n1\n", encoding="utf-8")
    second.write_text("value\n2\n", encoding="utf-8")
    first_ref = store.put_file(first, key="raw/a/first.csv", content_type="text/csv")
    second_ref = store.put_file(second, key="raw/b/second.csv", content_type="text/csv")

    try:
        asyncio.run(
            service.submit_uploaded_dataset(
                name="First",
                source_key=first_ref.key,
                source_format="csv",
                idempotency_key="same-key",
            )
        )
        with pytest.raises(ControlPlaneError, match="different upload data"):
            asyncio.run(
                service.submit_uploaded_dataset(
                    name="Second",
                    source_key=second_ref.key,
                    source_format="csv",
                    idempotency_key="same-key",
                )
            )
    finally:
        database.dispose()

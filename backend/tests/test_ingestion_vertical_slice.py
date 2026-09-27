from pathlib import Path

from analytica_api.config import Settings
from analytica_api.domain.control_plane import JobStatus
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.local import LocalArtifactStore


def test_queued_csv_becomes_registered_parquet_and_preview(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'vertical.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    control_plane = ControlPlaneService(
        lambda: SqlAlchemyUnitOfWork(database.session_factory)
    )
    ingestion = DatasetIngestionService(
        control_plane=control_plane,
        artifact_store=store,
        ingestion_engine=IngestionEngine(settings),
    )
    preview = DatasetPreviewService(
        control_plane=control_plane,
        artifact_store=store,
    )

    upload = tmp_path / "customers.csv"
    upload.write_text("name,age\nAda,36\nGrace,40\n", encoding="utf-8")
    uploaded_ref = store.put_file(
        upload,
        key="datasets/source/customers.csv",
        content_type="text/csv",
    )
    verified_ref = store.stat(uploaded_ref.key)

    try:
        created = control_plane.create_ingestion_job(
            dataset_name="Customers",
            source_ref=verified_ref,
            source_format="csv",
            idempotency_key="ingest:customers",
        )
        repeated = control_plane.create_ingestion_job(
            dataset_name="Ignored on retry",
            source_ref=verified_ref,
            source_format="csv",
            idempotency_key="ingest:customers",
        )
        assert repeated.dataset.id == created.dataset.id
        assert repeated.job.id == created.job.id
        assert created.job.status == JobStatus.QUEUED

        version_id = ingestion.run_job(created.job.id)
        replay_version_id = ingestion.run_job(created.job.id)
        completed = control_plane.get_job(created.job.id)
        dataset_preview = preview.preview(version_id, limit=10)

        assert completed.status == JobStatus.SUCCEEDED
        assert completed.attempt_count == 1
        assert completed.output_version_id == version_id
        assert replay_version_id == version_id
        assert dataset_preview.columns == ("name", "age")
        assert dataset_preview.rows == (("Ada", 36), ("Grace", 40))
    finally:
        database.dispose()

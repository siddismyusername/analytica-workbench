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


def test_uploaded_csv_becomes_registered_parquet_and_preview(tmp_path: Path) -> None:
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
    source_ref = store.put_file(
        upload,
        key="uploads/customers.csv",
        content_type="text/csv",
    )

    try:
        result = ingestion.ingest_uploaded_dataset(
            name="Customers",
            source_ref=source_ref,
            source_format="csv",
            idempotency_key="upload:customers:1",
        )
        repeated = ingestion.ingest_uploaded_dataset(
            name="Customers",
            source_ref=source_ref,
            source_format="csv",
            idempotency_key="upload:customers:1",
        )
        dataset_preview = preview.preview(result.version_id, limit=10)

        assert result.job.status == JobStatus.SUCCEEDED
        assert repeated.job.id == result.job.id
        assert repeated.dataset_id == result.dataset_id
        assert repeated.version_id == result.version_id
        assert dataset_preview.columns == ("name", "age")
        assert dataset_preview.rows == (("Ada", 36), ("Grace", 40))
    finally:
        database.dispose()

import asyncio
from pathlib import Path

from analytica_api.config import Settings
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.profile import DatasetProfileService
from analytica_api.storage.local import LocalArtifactStore


def test_profile_reports_missing_duplicates_and_constant_columns(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'profile.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    control_plane = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    worker = IngestionWorker(settings=settings, control_plane=control_plane, store=store)
    ingestion = DatasetIngestionService(
        settings=settings,
        control_plane=control_plane,
        artifact_store=store,
        job_queue=InlineJobQueue(worker.run),
    )
    profiler = DatasetProfileService(
        control_plane=control_plane,
        artifact_store=store,
    )

    upload = tmp_path / "customers.csv"
    upload.write_text(
        "name,age,segment\nAda,36,A\nGrace,,A\nAda,36,A\n",
        encoding="utf-8",
    )
    source_ref = store.put_file(
        upload,
        key="raw/profile/customers.csv",
        content_type="text/csv",
    )

    try:
        submission = asyncio.run(
            ingestion.submit_uploaded_dataset(
                name="Customers",
                source_key=source_ref.key,
            )
        )
        job = control_plane.get_job(submission.job.id)
        assert job.output_version_id is not None

        profile = profiler.profile(job.output_version_id)
        by_name = {column.name: column for column in profile.columns}
        warning_codes = {warning.code for warning in profile.warnings}

        assert profile.dataset_name == "Customers"
        assert profile.row_count == 3
        assert profile.column_count == 3
        assert profile.missing_cells == 1
        assert profile.missing_percentage == 11.11
        assert profile.duplicate_rows == 1
        assert profile.duplicate_percentage == 33.33
        assert by_name["age"].null_count == 1
        assert by_name["age"].null_percentage == 33.33
        assert by_name["segment"].distinct_count == 1
        assert warning_codes == {"missing_values", "duplicate_rows", "constant_columns"}
    finally:
        database.dispose()

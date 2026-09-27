import asyncio
from pathlib import Path

from analytica_api.config import Settings
from analytica_api.operations.models import (
    CastColumnOperation,
    DeduplicateOperation,
    FillNullOperation,
    FilterOperation,
    RenameColumnOperation,
)
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.services.transform import DatasetTransformService
from analytica_api.services.transform_worker import TransformWorker
from analytica_api.storage.local import LocalArtifactStore


def _stack(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'transform.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    control_plane = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    ingestion_worker = IngestionWorker(
        settings=settings,
        control_plane=control_plane,
        store=store,
    )
    transform_worker = TransformWorker(control_plane=control_plane, store=store)
    queue = InlineJobQueue(ingestion_worker.run, transform_worker.run)
    ingestion = DatasetIngestionService(
        settings=settings,
        control_plane=control_plane,
        artifact_store=store,
        job_queue=queue,
    )
    transform = DatasetTransformService(
        control_plane=control_plane,
        artifact_store=store,
        job_queue=queue,
    )
    preview = DatasetPreviewService(control_plane=control_plane, artifact_store=store)
    return database, store, control_plane, ingestion, transform, preview


def _ingest(tmp_path: Path, store, ingestion, control_plane):
    upload = tmp_path / "customers.csv"
    upload.write_text(
        "name,age,segment\nAda,36,A\nGrace,,B\nAda,36,A\n",
        encoding="utf-8",
    )
    source = store.put_file(upload, key="raw/prepare/customers.csv", content_type="text/csv")
    submission = asyncio.run(
        ingestion.submit_uploaded_dataset(name="Customers", source_key=source.key)
    )
    job = control_plane.get_job(submission.job.id)
    assert job.output_version_id is not None
    return job.output_version_id


def test_preview_is_read_only_and_apply_creates_child_version(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, transform, preview = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        original = control_plane.get_version(version_id)
        schema = original.schema_snapshot["columns"]
        age_id = next(
            column["column_id"]
            for column in schema
            if column["physical_name"] == "age"
        )
        operation = FillNullOperation(
            operation_id="fill-age",
            column_id=age_id,
            value=0,
        )

        before_counter = control_plane.get_dataset(original.dataset_id).next_version_number
        transform_preview = transform.preview(version_id, operation, limit=10)
        after_counter = control_plane.get_dataset(original.dataset_id).next_version_number
        assert before_counter == after_counter == 2
        assert transform_preview.input_row_count == 3
        assert transform_preview.output_row_count == 3
        assert transform_preview.rows[1][1] == 0

        submission = asyncio.run(transform.submit(version_id, operation))
        completed = control_plane.get_job(submission.job.id)
        assert completed.output_version_id is not None
        derived = control_plane.get_version(completed.output_version_id)
        assert derived.parent_version_id == version_id
        assert derived.version_number == 2

        original_preview = preview.preview(version_id, limit=10)
        derived_preview = preview.preview(derived.id, limit=10)
        assert original_preview.rows[1][1] is None
        assert derived_preview.rows[1][1] == 0

        history = transform.history(derived.id)
        assert len(history) == 1
        assert history[0].input_version_id == version_id
        assert history[0].output_version_id == derived.id
        assert history[0].operation["type"] == "fill_null"
    finally:
        database.dispose()


def test_prepare_operations_chain_through_immutable_versions(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, transform, preview = _stack(tmp_path)
    try:
        current = _ingest(tmp_path, store, ingestion, control_plane)
        schema = control_plane.get_version(current).schema_snapshot["columns"]
        name_id = next(
            column["column_id"]
            for column in schema
            if column["physical_name"] == "name"
        )
        age_id = next(
            column["column_id"]
            for column in schema
            if column["physical_name"] == "age"
        )

        operations = [
            DeduplicateOperation(operation_id="dedupe"),
            RenameColumnOperation(
                operation_id="rename",
                column_id=name_id,
                new_name="customer",
            ),
            CastColumnOperation(
                operation_id="cast",
                column_id=age_id,
                target_type="float",
            ),
            FilterOperation(
                operation_id="filter",
                column_id=name_id,
                operator="eq",
                value="Ada",
            ),
        ]
        for operation in operations:
            submitted = asyncio.run(transform.submit(current, operation))
            job = control_plane.get_job(submitted.job.id)
            assert job.output_version_id is not None
            current = job.output_version_id

        final = control_plane.get_version(current)
        final_preview = preview.preview(current, limit=10)
        assert final.version_number == 5
        assert final_preview.columns == ("customer", "age", "segment")
        assert final_preview.rows == (("Ada", 36.0, "A"),)
        history = transform.history(current)
        assert [item.operation["type"] for item in history] == [
            "deduplicate",
            "rename_column",
            "cast_column",
            "filter",
        ]
    finally:
        database.dispose()

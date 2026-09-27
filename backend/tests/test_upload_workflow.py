from pathlib import Path

from fastapi.testclient import TestClient

from analytica_api.config import Settings, get_settings
from analytica_api.main import create_app
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.runtime import get_artifact_store, get_control_plane, get_job_queue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.storage.local import LocalArtifactStore


def test_upload_completion_ingests_once_and_exposes_bounded_preview(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        environment="test",
        database_url=str(database.engine.url),
        local_artifact_root=str(tmp_path / "artifacts"),
        artifact_store_provider="local",
        queue_provider="inline",
        preview_max_rows=50,
        duckdb_threads=1,
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
    control_plane = ControlPlaneService(
        lambda: SqlAlchemyUnitOfWork(database.session_factory)
    )
    worker = IngestionWorker(
        settings=settings,
        control_plane=control_plane,
        store=store,
    )
    queue = InlineJobQueue(worker.run)

    raw_source = tmp_path / "customers.csv"
    raw_source.write_text(
        "customer_id,city,score\n1,Pune,10.5\n2,Mumbai,12.0\n3,Pune,9.0\n",
        encoding="utf-8",
    )
    raw = store.put_file(
        raw_source,
        key="raw/upload-one/source.csv",
        content_type="text/csv",
    )
    assert store.stat(raw.key).byte_size == raw.byte_size

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_control_plane] = lambda: control_plane
    app.dependency_overrides[get_artifact_store] = lambda: store
    app.dependency_overrides[get_job_queue] = lambda: queue

    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/v1/datasets/uploads/complete",
                json={
                    "dataset_name": "Customers",
                    "storage_key": raw.key,
                },
            )
            assert first.status_code == 202, first.text
            payload = first.json()
            assert payload["job_status"] == "succeeded"
            assert payload["output_version_id"] is not None

            repeated = client.post(
                "/api/v1/datasets/uploads/complete",
                json={
                    "dataset_name": "Ignored on idempotent retry",
                    "storage_key": raw.key,
                },
            )
            assert repeated.status_code == 202, repeated.text
            retry_payload = repeated.json()
            assert retry_payload["dataset_id"] == payload["dataset_id"]
            assert retry_payload["job_id"] == payload["job_id"]
            assert retry_payload["output_version_id"] == payload["output_version_id"]

            job = client.get(f"/api/v1/jobs/{payload['job_id']}")
            assert job.status_code == 200
            assert job.json()["status"] == "succeeded"
            assert job.json()["attempt_count"] == 1

            preview = client.get(
                "/api/v1/datasets/"
                f"{payload['dataset_id']}/versions/{payload['output_version_id']}/preview",
                params={"limit": 2, "offset": 1},
            )
            assert preview.status_code == 200, preview.text
            preview_payload = preview.json()
            assert preview_payload["total_rows"] == 3
            assert preview_payload["returned_rows"] == 2
            assert preview_payload["offset"] == 1
            assert preview_payload["rows"] == [
                {"customer_id": 2, "city": "Mumbai", "score": 12.0},
                {"customer_id": 3, "city": "Pune", "score": 9.0},
            ]

            too_large = client.get(
                "/api/v1/datasets/"
                f"{payload['dataset_id']}/versions/{payload['output_version_id']}/preview",
                params={"limit": 51},
            )
            assert too_large.status_code == 400
    finally:
        database.dispose()

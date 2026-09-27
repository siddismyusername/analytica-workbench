from pathlib import Path

from fastapi.testclient import TestClient

from analytica_api.config import Settings, get_settings
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.main import create_app
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.runtime import (
    get_artifact_store,
    get_control_plane,
    get_job_queue,
    get_preview_service,
)
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.local import LocalArtifactStore


def test_api_verifies_storage_enqueues_and_previews(tmp_path: Path) -> None:
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(database.engine)
    settings = Settings(
        environment="test",
        database_url=str(database.engine.url),
        artifact_store_backend="local",
        local_artifact_root=str(tmp_path / "artifacts"),
        queue_backend="inline",
        duckdb_threads=1,
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
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
    queue = InlineJobQueue(ingestion.run_job)

    source = tmp_path / "customers.csv"
    source.write_text("name,age\nAda,36\nGrace,40\n", encoding="utf-8")
    uploaded = store.put_file(
        source,
        key="datasets/source/customers.csv",
        content_type="text/csv",
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_control_plane] = lambda: control_plane
    app.dependency_overrides[get_artifact_store] = lambda: store
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_preview_service] = lambda: preview

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/datasets/ingestions",
                json={"name": "Customers", "source_key": uploaded.key},
            )
            assert response.status_code == 202, response.text
            result = response.json()
            assert result["status"] == "succeeded"
            assert result["version_id"] is not None

            repeated = client.post(
                "/api/v1/datasets/ingestions",
                json={"name": "Different name", "source_key": uploaded.key},
            )
            assert repeated.status_code == 202
            assert repeated.json()["dataset_id"] == result["dataset_id"]
            assert repeated.json()["job_id"] == result["job_id"]
            assert repeated.json()["version_id"] == result["version_id"]

            job = client.get(f"/api/v1/jobs/{result['job_id']}")
            assert job.status_code == 200
            assert job.json()["status"] == "succeeded"

            preview_response = client.get(
                f"/api/v1/datasets/versions/{result['version_id']}/preview",
                params={"limit": 1, "offset": 1},
            )
            assert preview_response.status_code == 200, preview_response.text
            assert preview_response.json()["columns"] == ["name", "age"]
            assert preview_response.json()["rows"] == [["Grace", 40]]

            missing = client.post(
                "/api/v1/datasets/ingestions",
                json={
                    "name": "Missing",
                    "source_key": "datasets/source/missing.csv",
                },
            )
            assert missing.status_code == 400
    finally:
        database.dispose()

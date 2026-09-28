from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from analytica_api import runtime
from analytica_api.config import get_settings
from analytica_api.main import create_app


def _clear_runtime() -> None:
    for factory in (
        runtime.get_analyze_service,
        runtime.get_explore_service,
        runtime.get_profile_service,
        runtime.get_preview_service,
        runtime.get_transform_service,
        runtime.get_ingestion_service,
        runtime.get_job_queue,
        runtime.get_transform_worker,
        runtime.get_ingestion_worker,
        runtime.get_artifact_store,
        runtime.get_control_plane,
        runtime.get_database,
        get_settings,
    ):
        factory.cache_clear()


def test_local_http_upload_ingestion_and_preview(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'local.db'}"
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ARTIFACT_STORE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("QUEUE_PROVIDER", "inline")
    _clear_runtime()

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    try:
        with TestClient(create_app()) as client:
            upload_id = uuid4()
            pathname = f"raw/{upload_id}/sample.csv"
            upload = client.put(
                f"/api/v1/datasets/uploads/local/{upload_id}/sample.csv",
                content=b"name,age\nAda,36\nGrace,40\n",
                headers={"Content-Type": "text/csv"},
            )
            assert upload.status_code == 201
            assert upload.json()["source_key"] == pathname

            ingestion = client.post(
                "/api/v1/datasets/ingestions",
                json={"name": "Sample", "source_key": pathname},
            )
            assert ingestion.status_code == 202
            assert ingestion.json()["status"] == "succeeded"
            version_id = ingestion.json()["version_id"]

            profile = client.get(f"/api/v1/datasets/versions/{version_id}/profile")
            preview = client.get(f"/api/v1/datasets/versions/{version_id}/preview")
            assert profile.status_code == preview.status_code == 200
            assert profile.json()["row_count"] == 2
            assert preview.json()["rows"] == [["Ada", 36], ["Grace", 40]]
    finally:
        runtime.get_database().dispose()
        _clear_runtime()


def test_local_upload_is_unavailable_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ARTIFACT_STORE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    _clear_runtime()
    try:
        with TestClient(create_app()) as client:
            response = client.put(
                f"/api/v1/datasets/uploads/local/{uuid4()}/sample.csv",
                content=b"value\n1\n",
                headers={"Content-Type": "text/csv"},
            )
            assert response.status_code == 404
    finally:
        _clear_runtime()

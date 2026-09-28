from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "analytica-workbench-api",
    }


def test_openapi_is_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Analytica Workbench API"


def test_capabilities_report_active_deferred_jobs() -> None:
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["execution"]["deferred_jobs"] == [
        "ingestion",
        "transform",
        "model_train",
    ]

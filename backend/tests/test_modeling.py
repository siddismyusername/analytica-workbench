import asyncio
import pickle
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.model_selection import train_test_split
from sqlalchemy import delete

from analytica_api.config import Settings
from analytica_api.main import create_app
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base, SavedResultModel
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.routes import modeling as modeling_routes
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.modeling import (
    DatasetModelService,
    ModelRunConfig,
    ModelValidationError,
    ModelWorker,
)
from analytica_api.services.results import ResultsService
from analytica_api.storage.contracts import StorageObjectRef
from analytica_api.storage.local import LocalArtifactStore


def _stack(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'model.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    control = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    ingestion_worker = IngestionWorker(settings=settings, control_plane=control, store=store)
    model_worker = ModelWorker(control_plane=control, store=store)
    queue = InlineJobQueue(ingestion_worker.run, model_handler=model_worker.run)
    ingestion = DatasetIngestionService(
        settings=settings, control_plane=control, artifact_store=store, job_queue=queue
    )
    modeling = DatasetModelService(control_plane=control, store=store, queue=queue)
    csv = tmp_path / "training.csv"
    lines = ["age,segment,sales,churn"]
    for index in range(80):
        age = "" if index == 7 else str(20 + index % 35)
        segment = "" if index == 11 else ("A" if index % 2 else "B")
        lines.append(
            f"{age},{segment},{100 + index * 3 + index % 2},{'yes' if index % 2 else 'no'}"
        )
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    source = store.put_file(csv, key="raw/model/training.csv", content_type="text/csv")
    submitted = asyncio.run(
        ingestion.submit_uploaded_dataset(name="Training", source_key=source.key)
    )
    version_id = control.get_job(submitted.job.id).output_version_id
    assert version_id is not None
    schema = control.get_version(version_id).schema_snapshot["columns"]
    ids = {column["physical_name"]: column["column_id"] for column in schema}
    return database, store, control, modeling, version_id, ids


@pytest.mark.parametrize(
    ("problem_type", "target", "primary_metric"),
    [("regression", "sales", "rmse"), ("classification", "churn", "macro_f1")],
)
def test_model_run_is_durable_and_version_bound(
    tmp_path: Path, problem_type: str, target: str, primary_metric: str
) -> None:
    database, store, control, modeling, version_id, ids = _stack(tmp_path)
    try:
        config = ModelRunConfig(
            problem_type=problem_type,
            target_column_id=ids[target],
            feature_column_ids=(ids["age"], ids["segment"]),
            algorithms=("linear", "decision_tree"),
            cross_validation=True,
        )
        job = asyncio.run(modeling.submit(version_id, config))
        assert job.status.value == "succeeded"
        result = modeling.result(job.id)
        assert result is not None
        assert result["version_id"] == str(version_id)
        assert result["primary_metric"] == primary_metric
        assert result["validation_method"] == "3-fold training cross-validation"
        assert [candidate["algorithm"] for candidate in result["candidates"]] == [
            "baseline",
            "linear",
            "decision_tree",
        ]
        assert result["train_rows"] + result["test_rows"] == 80
        assert result["explanation"]
        assert all(candidate["cv_score"] is not None for candidate in result["candidates"])
        validation_scores = [
            candidate["validation_score"] for candidate in result["candidates"][1:]
        ]
        selected_score = next(
            candidate["validation_score"]
            for candidate in result["candidates"]
            if candidate["algorithm"] == result["best_algorithm"]
        )
        assert selected_score == (
            min(validation_scores) if problem_type == "regression" else max(validation_scores)
        )
        assert control.get_artifact_for_job_kind(job.id, "model_pipeline").byte_size > 0
        assert control.get_artifact_for_job_kind(job.id, "model_evaluation").byte_size > 0
        saved = control.list_results(version_id)
        assert len(saved) == 1
        assert saved[0].source_job_id == job.id
        assert saved[0].payload == result
        assert len(control.list_jobs_for_version(version_id, "model_train")) == 1
        assert control.get_version(version_id).version_number == 1
        repeated = asyncio.run(modeling.submit(version_id, config))
        assert repeated.id == job.id
        assert repeated.attempt_count == 1
        assert len(control.list_results(version_id)) == 1
        if problem_type == "regression":
            artifact = control.get_artifact_for_job_kind(job.id, "model_pipeline")
            path = store.materialize(
                StorageObjectRef(
                    key=artifact.storage_key,
                    byte_size=artifact.byte_size,
                    content_type=artifact.content_type,
                    checksum_sha256=artifact.checksum_sha256,
                ),
                tmp_path / "saved-pipeline.pkl",
            )
            pipeline = pickle.loads(path.read_bytes())  # trusted artifact created in this test
            numeric = pipeline.named_steps["preprocess"].named_transformers_["numeric"]
            fitted_mean = numeric.named_steps["scale"].mean_[0]
            original = pd.read_csv(tmp_path / "training.csv")["age"]
            training, _ = train_test_split(original, test_size=0.2, random_state=42)
            expected = training.fillna(training.median()).mean()
            assert fitted_mean == pytest.approx(expected)
            assert fitted_mean != pytest.approx(original.fillna(original.median()).mean())
    finally:
        database.dispose()


def test_model_rejects_incompatible_target_and_missing_predictor(tmp_path: Path) -> None:
    database, _, _, modeling, version_id, ids = _stack(tmp_path)
    try:
        with pytest.raises(ModelValidationError, match="numeric target"):
            asyncio.run(
                modeling.submit(
                    version_id,
                    ModelRunConfig(
                        problem_type="regression",
                        target_column_id=ids["churn"],
                        feature_column_ids=(ids["age"],),
                    ),
                )
            )
        with pytest.raises(ModelValidationError, match="predictor does not exist"):
            asyncio.run(
                modeling.submit(
                    version_id,
                    ModelRunConfig(
                        problem_type="classification",
                        target_column_id=ids["churn"],
                        feature_column_ids=("missing-id",),
                    ),
                )
            )
    finally:
        database.dispose()


def test_model_http_submit_and_reopen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, _, control, modeling, version_id, ids = _stack(tmp_path)
    monkeypatch.setattr(modeling_routes, "get_model_service", lambda: modeling)
    monkeypatch.setattr(modeling_routes, "get_control_plane", lambda: control)
    try:
        client = TestClient(create_app())
        url = f"/api/v1/datasets/versions/{version_id}/models/runs"
        response = client.post(
            url,
            json={
                "problem_type": "classification",
                "target_column_id": ids["churn"],
                "feature_column_ids": [ids["age"], ids["segment"]],
                "algorithms": ["linear"],
            },
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["result"]["best_algorithm"] == "linear"
        assert payload["result"]["validation_method"] == "training holdout"
        assert payload["artifacts"]["model_pipeline"]
        listed = client.get(url)
        reopened = client.get(f"/api/v1/models/runs/{payload['job_id']}")
        assert listed.status_code == reopened.status_code == 200
        assert listed.json()[0]["result"] == reopened.json()["result"]
        assert (
            client.post(url, json={**payload["configuration"], "unexpected": True}).status_code
            == 422
        )
    finally:
        database.dispose()


def test_invalid_training_data_returns_a_failed_durable_run(tmp_path: Path) -> None:
    database, _, control, modeling, version_id, ids = _stack(tmp_path)
    try:
        job = asyncio.run(
            modeling.submit(
                version_id,
                ModelRunConfig(
                    problem_type="classification",
                    target_column_id=ids["sales"],
                    feature_column_ids=(ids["age"],),
                    algorithms=("linear",),
                ),
            )
        )
        assert job.status.value == "failed"
        assert job.error_detail is not None
        assert "2 to 20" in job.error_detail["message"]
        assert modeling.result(job.id) is None
        assert control.get_job(job.id).status.value == "failed"
    finally:
        database.dispose()


def test_model_subscriber_is_registered_for_deployment() -> None:
    manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    entrypoints = [item["entrypoint"] for item in manifest["tool"]["vercel"]["subscribers"]]
    assert "analytica_api.queue.subscribers:train_model" in entrypoints


def test_previous_model_run_is_recovered_from_saved_evaluation(tmp_path: Path) -> None:
    database, store, control, modeling, version_id, ids = _stack(tmp_path)
    try:
        job = asyncio.run(
            modeling.submit(
                version_id,
                ModelRunConfig(
                    problem_type="regression",
                    target_column_id=ids["sales"],
                    feature_column_ids=(ids["age"],),
                    algorithms=("linear",),
                ),
            )
        )
        assert job.status.value == "succeeded"
        with database.session_factory() as session:
            session.execute(
                delete(SavedResultModel).where(SavedResultModel.source_job_id == job.id)
            )
            session.commit()
        service = ResultsService(
            control_plane=control, store=store, queue=InlineJobQueue(lambda _job_id: None)
        )
        saved = service.list_results(version_id)
        assert len(saved) == 1
        assert saved[0].source_job_id == job.id
        assert saved[0].payload == modeling.result(job.id)
        assert service.list_results(version_id) == saved
    finally:
        database.dispose()

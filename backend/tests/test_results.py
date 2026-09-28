import asyncio
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analytica_api.config import Settings
from analytica_api.main import create_app
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.routes import analyze as analyze_routes
from analytica_api.routes import explore as explore_routes
from analytica_api.routes import results as results_routes
from analytica_api.services.analyze import DatasetAnalyzeService
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.explore import DatasetExploreService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.results import ExportWorker, ResultsService, chart_svg
from analytica_api.storage.local import LocalArtifactStore


def test_saved_results_report_and_dataset_exports_survive_reopen(tmp_path, monkeypatch):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'results.db'}")
    Base.metadata.create_all(database.engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    control = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    settings = Settings(environment="test", local_artifact_root=str(tmp_path / "artifacts"))
    ingestion_worker = IngestionWorker(settings=settings, control_plane=control, store=store)
    export_worker = ExportWorker(control_plane=control, store=store)
    queue = InlineJobQueue(ingestion_worker.run, export_handler=export_worker.run)
    ingestion = DatasetIngestionService(
        settings=settings, control_plane=control, artifact_store=store, job_queue=queue
    )
    analysis = DatasetAnalyzeService(control_plane=control, artifact_store=store)
    exploration = DatasetExploreService(control_plane=control, artifact_store=store)
    result_service = ResultsService(control_plane=control, store=store, queue=queue)
    monkeypatch.setattr(analyze_routes, "get_analyze_service", lambda: analysis)
    monkeypatch.setattr(analyze_routes, "get_control_plane", lambda: control)
    monkeypatch.setattr(explore_routes, "get_explore_service", lambda: exploration)
    monkeypatch.setattr(explore_routes, "get_control_plane", lambda: control)
    monkeypatch.setattr(results_routes, "get_control_plane", lambda: control)
    monkeypatch.setattr(results_routes, "get_results_service", lambda: result_service)
    monkeypatch.setattr(results_routes, "get_artifact_store", lambda: store)
    try:
        csv = tmp_path / "source.csv"
        csv.write_text(
            "name,value\n" + "".join(f"row-{index},{index}\n" for index in range(40)),
            encoding="utf-8",
        )
        source = store.put_file(csv, key="raw/results/source.csv", content_type="text/csv")
        submission = asyncio.run(
            ingestion.submit_uploaded_dataset(name="Results", source_key=source.key)
        )
        version_id = control.get_job(submission.job.id).output_version_id
        assert version_id is not None
        column_id = next(
            column["column_id"]
            for column in control.get_version(version_id).schema_snapshot["columns"]
            if column["physical_name"] == "value"
        )
        client = TestClient(create_app())
        prefix = f"/api/v1/datasets/versions/{version_id}"
        run = client.post(
            prefix + "/analyze/run",
            json={"test_id": "one_sample_t", "x_column_id": column_id, "reference_value": 20},
        )
        assert run.status_code == 200, run.text
        analysis_id = run.json()["saved_result_id"]
        assert analysis_id
        repeated = client.post(
            prefix + "/analyze/run",
            json={"test_id": "one_sample_t", "x_column_id": column_id, "reference_value": 20},
        )
        assert repeated.json()["saved_result_id"] == analysis_id
        chart = client.post(
            prefix + "/explore/visualizations",
            json={"chart_type": "histogram", "x_column_id": column_id},
        )
        assert chart.status_code == 200, chart.text
        reopened = ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))
        saved = reopened.list_results(version_id)
        assert len(saved) == 2
        chart_id = next(item.id for item in saved if item.kind == "chart")
        assert client.get(prefix + "/results").status_code == 200
        assert (
            client.get(f"/api/v1/results/{analysis_id}").json()["payload"]["p_value"]
            == run.json()["p_value"]
        )

        def analysis_must_not_run(*_args, **_kwargs):
            raise AssertionError("report export must use the saved result")

        monkeypatch.setattr(analysis, "run", analysis_must_not_run)

        report = client.post(
            prefix + "/exports",
            json={
                "kind": "report_html",
                "title": "<Report>",
                "result_ids": [analysis_id, str(chart_id)],
            },
        )
        assert report.status_code == 202, report.text
        assert report.json()["status"] == "succeeded"
        report_bytes = client.get(
            f"/api/v1/artifacts/{report.json()['artifact_id']}/download"
        ).content
        assert b"&lt;Report&gt;" in report_bytes
        assert b"<svg" in report_bytes
        assert str(analysis_id).encode() in report_bytes
        assert str(chart_id).encode() in report_bytes
        assert b"one_sample_t" in report_bytes
        assert (
            client.get(f"/api/v1/exports/{report.json()['job_id']}").json()["artifact_id"]
            == report.json()["artifact_id"]
        )
        assert (
            client.post(
                prefix + "/exports",
                json={
                    "kind": "report_html",
                    "title": "<Report>",
                    "result_ids": [analysis_id, str(chart_id)],
                },
            ).json()["job_id"]
            == report.json()["job_id"]
        )

        csv_export = client.post(prefix + "/exports", json={"kind": "dataset_csv"}).json()
        parquet_export = client.post(prefix + "/exports", json={"kind": "dataset_parquet"}).json()
        svg_export = client.post(
            prefix + "/exports", json={"kind": "chart_svg", "result_ids": [str(chart_id)]}
        ).json()
        assert (
            csv_export["status"] == parquet_export["status"] == svg_export["status"] == "succeeded"
        )
        assert (
            b"name,value"
            in client.get(f"/api/v1/artifacts/{csv_export['artifact_id']}/download").content
        )
        assert (
            client.get(f"/api/v1/artifacts/{parquet_export['artifact_id']}/download").content[:4]
            == b"PAR1"
        )
        assert (
            b"<svg" in client.get(f"/api/v1/artifacts/{svg_export['artifact_id']}/download").content
        )
        assert len(client.get(prefix + "/exports").json()) == 3
        assert (
            client.post(
                prefix + "/exports",
                json={
                    "kind": "report_html",
                    "title": "Bad",
                    "result_ids": [analysis_id, analysis_id],
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                prefix + "/exports", json={"kind": "chart_svg", "result_ids": [analysis_id]}
            ).status_code
            == 422
        )
        second_source = store.put_file(csv, key="raw/results/second.csv", content_type="text/csv")
        second = asyncio.run(
            ingestion.submit_uploaded_dataset(name="Second", source_key=second_source.key)
        )
        second_version = control.get_job(second.job.id).output_version_id
        assert second_version is not None
        assert (
            client.post(
                f"/api/v1/datasets/versions/{second_version}/exports",
                json={"kind": "report_html", "title": "Mixed", "result_ids": [analysis_id]},
            ).status_code
            == 422
        )
        raw_artifact = control.get_artifact_for_job_kind(submission.job.id, "raw_upload")
        assert client.get(f"/api/v1/artifacts/{raw_artifact.id}/download").status_code == 404
    finally:
        database.dispose()


def test_export_subscriber_registered() -> None:
    manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    entrypoints = [item["entrypoint"] for item in manifest["tool"]["vercel"]["subscribers"]]
    assert "analytica_api.queue.subscribers:export_results" in entrypoints


@pytest.mark.parametrize(
    ("chart_type", "data"),
    [
        ("bar", [{"category": "A", "value": 2}]),
        ("histogram", [{"start": 0, "end": 1, "count": 2}]),
        ("line", [{"x": "Monday", "y": 2}, {"x": "Tuesday", "y": 4}]),
        ("scatter", [{"x": 1, "y": 2}]),
        ("qq", [{"x": 1, "y": 2}]),
        ("box", [{"category": "A", "values": [1, 2, 3, 4, 5]}]),
        ("heatmap", [{"x": "A", "y": "B", "value": 0.8}]),
    ],
)
def test_supported_chart_exports_have_svg_marks(chart_type, data) -> None:
    svg = chart_svg({"chart_type": chart_type, "title": "A & B", "data": data})
    assert svg.startswith("<svg")
    assert "A &amp; B" in svg
    assert "<rect" in svg or "<circle" in svg or "<path" in svg

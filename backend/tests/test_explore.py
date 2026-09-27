import asyncio
from pathlib import Path

from analytica_api.config import Settings
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.explore import DatasetExploreService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.transform_worker import TransformWorker
from analytica_api.storage.local import LocalArtifactStore


def _stack(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'explore.db'}")
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
    explore = DatasetExploreService(
        control_plane=control_plane,
        artifact_store=store,
    )
    return database, store, control_plane, ingestion, explore


def _ingest(tmp_path: Path, store, ingestion, control_plane):
    upload = tmp_path / "explore.csv"
    upload.write_text(
        "segment,region,age,income\n"
        "A,North,20,100\n"
        "A,South,30,200\n"
        "B,North,40,300\n"
        "B,South,50,400\n"
        "B,South,60,500\n",
        encoding="utf-8",
    )
    source = store.put_file(upload, key="raw/explore/data.csv", content_type="text/csv")
    submission = asyncio.run(
        ingestion.submit_uploaded_dataset(name="Explore data", source_key=source.key)
    )
    job = control_plane.get_job(submission.job.id)
    assert job.output_version_id is not None
    return job.output_version_id


def _column_ids(control_plane, version_id):
    schema = control_plane.get_version(version_id).schema_snapshot["columns"]
    return {column["physical_name"]: column["column_id"] for column in schema}


def test_descriptives_frequencies_correlations_and_crosstab(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, explore = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        descriptive = explore.describe(version_id, columns["age"])
        assert descriptive.valid_count == 5
        assert descriptive.mean == 40.0
        assert descriptive.median == 40.0
        assert descriptive.minimum == 20
        assert descriptive.maximum == 60

        frequencies = explore.frequencies(version_id, columns["segment"])
        assert frequencies.items[0].value == "B"
        assert frequencies.items[0].count == 3

        correlation = explore.correlation(
            version_id, (columns["age"], columns["income"])
        )
        assert correlation.matrix[0][1] == 1.0

        table = explore.crosstab(
            version_id,
            columns["segment"],
            columns["region"],
        )
        assert table.total == 5
        assert sum(table.row_totals) == 5
        assert sum(table.column_totals) == 5
    finally:
        database.dispose()


def test_visualization_payloads_are_bounded_and_chart_ready(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, explore = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        histogram = explore.visualization(
            version_id, "histogram", columns["age"], bins=5
        )
        assert histogram.chart_type == "histogram"
        assert sum(item["count"] for item in histogram.data) == 5

        scatter = explore.visualization(
            version_id,
            "scatter",
            columns["age"],
            y_column_id=columns["income"],
            limit=100,
        )
        assert len(scatter.data) == 5
        assert all("x" in item and "y" in item for item in scatter.data)

        box = explore.visualization(version_id, "box", columns["income"])
        assert box.data[0]["values"] == [100.0, 200.0, 300.0, 400.0, 500.0]

        qq = explore.visualization(
            version_id, "qq", columns["age"], limit=100
        )
        assert len(qq.data) == 5
        assert qq.metadata["sample_size"] == 5

        heatmap = explore.visualization(
            version_id, "heatmap", columns["age"]
        )
        assert heatmap.metadata["method"] == "pearson"
        assert len(heatmap.data) == 4
    finally:
        database.dispose()

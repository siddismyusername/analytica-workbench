import asyncio
from pathlib import Path

import pytest

from analytica_api.config import Settings
from analytica_api.persistence.database import Database
from analytica_api.persistence.models import Base
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.providers import InlineJobQueue
from analytica_api.services.analyze import DatasetAnalyzeService
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.transform_worker import TransformWorker
from analytica_api.storage.local import LocalArtifactStore


def _stack(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'analyze.db'}")
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
    analyze = DatasetAnalyzeService(
        control_plane=control_plane,
        artifact_store=store,
    )
    return database, store, control_plane, ingestion, analyze


def _ingest(tmp_path: Path, store, ingestion, control_plane):
    upload = tmp_path / "analyze.csv"
    upload.write_text(
        "arm,group,category,x,y,before,after\n"
        "A,G1,N,10,2,12,10\n"
        "A,G1,N,12,3,14,11\n"
        "A,G1,S,11,4,13,11\n"
        "B,G2,N,20,6,22,18\n"
        "B,G2,S,22,7,24,20\n"
        "B,G2,S,21,8,23,19\n"
        "B,G3,N,30,10,33,29\n"
        "B,G3,N,31,11,34,30\n"
        "B,G3,S,29,12,32,28\n",
        encoding="utf-8",
    )
    source = store.put_file(upload, key="raw/analyze/data.csv", content_type="text/csv")
    submission = asyncio.run(
        ingestion.submit_uploaded_dataset(name="Analyze data", source_key=source.key)
    )
    job = control_plane.get_job(submission.job.id)
    assert job.output_version_id is not None
    return job.output_version_id


def _column_ids(control_plane, version_id):
    schema = control_plane.get_version(version_id).schema_snapshot["columns"]
    return {column["physical_name"]: column["column_id"] for column in schema}


def test_recommendations_follow_goal_and_group_cardinality(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, analyze = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        two_group = analyze.recommend(
            version_id,
            "compare_groups",
            outcome_column_id=columns["x"],
            group_column_id=columns["arm"],
        )
        assert two_group.recommendations[0].test_id == "welch_t"
        assert two_group.recommendations[1].test_id == "mann_whitney"

        three_group = analyze.recommend(
            version_id,
            "compare_groups",
            outcome_column_id=columns["x"],
            group_column_id=columns["group"],
        )
        assert three_group.recommendations[0].test_id == "welch_anova"
        assert three_group.recommendations[1].test_id == "kruskal"

        relationship = analyze.recommend(
            version_id,
            "numeric_relationship",
            outcome_column_id=columns["x"],
            secondary_column_id=columns["y"],
        )
        assert [item.test_id for item in relationship.recommendations] == [
            "pearson",
            "spearman",
        ]
    finally:
        database.dispose()


def test_parametric_results_include_uncertainty_effects_and_diagnostics(
    tmp_path: Path,
) -> None:
    database, store, control_plane, ingestion, analyze = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        welch = analyze.run(
            version_id,
            "welch_t",
            x_column_id=columns["x"],
            group_column_id=columns["arm"],
        )
        assert welch.confidence_interval is not None
        assert welch.effect_size is not None
        assert welch.effect_size.name == "Hedges' g"
        assert welch.sample_size == 9
        assert any(item.name.startswith("Normality") for item in welch.diagnostics)
        assert {item.chart_type for item in welch.visualizations} == {"box", "qq"}

        paired = analyze.run(
            version_id,
            "paired_t",
            x_column_id=columns["before"],
            y_column_id=columns["after"],
        )
        assert paired.estimate is not None
        assert paired.estimate.value > 0
        assert paired.confidence_interval is not None
        assert paired.effect_size is not None

        one_sample = analyze.run(
            version_id,
            "one_sample_t",
            x_column_id=columns["x"],
            reference_value=20,
        )
        assert one_sample.confidence_interval is not None
        assert one_sample.statistic.degrees_of_freedom == pytest.approx(8.0)
    finally:
        database.dispose()


def test_nonparametric_and_anova_families_execute(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, analyze = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        welch_anova = analyze.run(
            version_id,
            "welch_anova",
            x_column_id=columns["x"],
            group_column_id=columns["group"],
        )
        assert welch_anova.statistic.name == "F"
        assert welch_anova.effect_size is not None
        assert len(welch_anova.group_summaries) == 3

        mann_whitney = analyze.run(
            version_id,
            "mann_whitney",
            x_column_id=columns["x"],
            group_column_id=columns["arm"],
        )
        assert mann_whitney.effect_size is not None
        assert mann_whitney.effect_size.name == "Rank-biserial correlation"

        wilcoxon = analyze.run(
            version_id,
            "wilcoxon",
            x_column_id=columns["before"],
            y_column_id=columns["after"],
        )
        assert wilcoxon.statistic.name == "W"

        kruskal = analyze.run(
            version_id,
            "kruskal",
            x_column_id=columns["x"],
            group_column_id=columns["group"],
        )
        assert kruskal.statistic.name == "H"
        assert kruskal.effect_size is not None
    finally:
        database.dispose()


def test_association_results_include_linked_diagnostic_visuals(tmp_path: Path) -> None:
    database, store, control_plane, ingestion, analyze = _stack(tmp_path)
    try:
        version_id = _ingest(tmp_path, store, ingestion, control_plane)
        columns = _column_ids(control_plane, version_id)

        pearson = analyze.run(
            version_id,
            "pearson",
            x_column_id=columns["x"],
            y_column_id=columns["y"],
        )
        assert pearson.confidence_interval is not None
        assert pearson.effect_size is not None
        assert pearson.visualizations[0].chart_type == "scatter"

        spearman = analyze.run(
            version_id,
            "spearman",
            x_column_id=columns["x"],
            y_column_id=columns["y"],
        )
        assert spearman.statistic.name == "ρ"
        assert spearman.visualizations[0].chart_type == "scatter"

        chi_square = analyze.run(
            version_id,
            "chi_square",
            x_column_id=columns["group"],
            y_column_id=columns["category"],
        )
        assert chi_square.statistic.name == "χ²"
        assert chi_square.effect_size is not None
        assert chi_square.effect_size.name == "Cramér's V"
        assert chi_square.visualizations[0].chart_type == "heatmap"
        assert chi_square.diagnostics[0].name == "Expected cell counts"
    finally:
        database.dispose()

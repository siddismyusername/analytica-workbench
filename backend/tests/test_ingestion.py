from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from analytica_api.config import Settings
from analytica_api.ingestion.engine import IngestionEngine, IngestionError


def _engine() -> IngestionEngine:
    return IngestionEngine(Settings(environment="test", duckdb_threads=1))


def test_csv_is_canonicalized_to_parquet_without_materializing_in_python(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    target = tmp_path / "canonical" / "data.parquet"
    source.write_text("age,city,score\n18,Pune,1.5\n25,,2.5\n", encoding="utf-8")

    manifest = _engine().ingest_local(source, target, source_format="csv")

    assert target.is_file()
    assert manifest.source_format == "csv"
    assert manifest.canonical_format == "parquet"
    assert manifest.row_count == 2
    assert manifest.byte_size > 0
    assert [column.physical_name for column in manifest.schema.columns] == [
        "age",
        "city",
        "score",
    ]
    assert [column.data_type for column in manifest.schema.columns] == [
        "integer",
        "string",
        "float",
    ]
    assert len({column.column_id for column in manifest.schema.columns}) == 3

    rows = duckdb.connect().execute(
        "SELECT age, city, score FROM read_parquet(?) ORDER BY age",
        [str(target)],
    ).fetchall()
    assert rows == [(18, "Pune", 1.5), (25, None, 2.5)]


def test_parquet_is_rewritten_as_independent_canonical_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    target = tmp_path / "canonical.parquet"
    pq.write_table(pa.table({"active": [True, False], "name": ["A", "B"]}), source)

    manifest = _engine().ingest_local(source, target, source_format="parquet")

    assert target.is_file()
    assert target != source
    assert manifest.row_count == 2
    assert [column.data_type for column in manifest.schema.columns] == [
        "boolean",
        "string",
    ]
    assert pq.read_table(target).to_pydict() == {
        "active": [True, False],
        "name": ["A", "B"],
    }


def test_ingestion_never_overwrites_existing_canonical_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    target = tmp_path / "data.parquet"
    source.write_text("value\n1\n", encoding="utf-8")
    target.write_bytes(b"existing")

    with pytest.raises(IngestionError, match="already exists"):
        _engine().ingest_local(source, target, source_format="csv")

    assert target.read_bytes() == b"existing"

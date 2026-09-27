from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_initial_control_plane_migration_round_trips_on_sqlite(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+pysqlite:///{database_path}"

    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"datasets", "dataset_versions", "jobs", "artifacts"} <= tables
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "datasets" not in tables
        assert "dataset_versions" not in tables
        assert "jobs" not in tables
        assert "artifacts" not in tables
    finally:
        engine.dispose()

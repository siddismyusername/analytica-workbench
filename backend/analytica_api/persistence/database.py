from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Database:
    """Own the SQLAlchemy engine and session factory without connecting at import time."""

    def __init__(self, database_url: str):
        engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if database_url in {"sqlite://", "sqlite+pysqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool

        self.engine: Engine = create_engine(database_url, **engine_kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    def dispose(self) -> None:
        self.engine.dispose()

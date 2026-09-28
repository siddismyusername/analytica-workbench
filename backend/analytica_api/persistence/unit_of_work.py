from collections.abc import Callable
from typing import Protocol, Self

from sqlalchemy.orm import Session

from analytica_api.persistence.repositories import (
    ArtifactRepository,
    DatasetRepository,
    DatasetVersionRepository,
    JobRepository,
    SavedResultRepository,
    SqlAlchemyArtifactRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyDatasetVersionRepository,
    SqlAlchemyJobRepository,
    SqlAlchemySavedResultRepository,
)


class UnitOfWork(Protocol):
    datasets: DatasetRepository
    versions: DatasetVersionRepository
    artifacts: ArtifactRepository
    jobs: JobRepository
    results: SavedResultRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> Self:
        self.session = self.session_factory()
        self.datasets = SqlAlchemyDatasetRepository(self.session)
        self.versions = SqlAlchemyDatasetVersionRepository(self.session)
        self.artifacts = SqlAlchemyArtifactRepository(self.session)
        self.jobs = SqlAlchemyJobRepository(self.session)
        self.results = SqlAlchemySavedResultRepository(self.session)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self.session is None:
            return
        if exc_type is not None:
            self.session.rollback()
        self.session.close()
        self.session = None

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        self.session.commit()

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        self.session.rollback()

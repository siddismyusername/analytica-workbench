from functools import lru_cache
from pathlib import Path

from analytica_api.config import get_settings
from analytica_api.ingestion.engine import IngestionEngine
from analytica_api.persistence.database import Database
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.contracts import JobQueue
from analytica_api.queue.providers import InlineJobQueue, VercelJobQueue
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.storage.contracts import ArtifactStore
from analytica_api.storage.local import LocalArtifactStore
from analytica_api.storage.vercel_blob import VercelBlobArtifactStore


@lru_cache(maxsize=1)
def get_database() -> Database:
    return Database(get_settings().database_url)


@lru_cache(maxsize=1)
def get_control_plane() -> ControlPlaneService:
    database = get_database()
    return ControlPlaneService(lambda: SqlAlchemyUnitOfWork(database.session_factory))


@lru_cache(maxsize=1)
def get_artifact_store() -> ArtifactStore:
    settings = get_settings()
    if settings.artifact_store_backend == "vercel_blob":
        return VercelBlobArtifactStore()
    return LocalArtifactStore(Path(settings.local_artifact_root))


@lru_cache(maxsize=1)
def get_ingestion_service() -> DatasetIngestionService:
    return DatasetIngestionService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
        ingestion_engine=IngestionEngine(get_settings()),
    )


@lru_cache(maxsize=1)
def get_preview_service() -> DatasetPreviewService:
    return DatasetPreviewService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_job_queue() -> JobQueue:
    if get_settings().queue_backend == "vercel":
        return VercelJobQueue()
    return InlineJobQueue(get_ingestion_service().run_job)

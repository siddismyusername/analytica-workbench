from functools import lru_cache
from pathlib import Path

from analytica_api.config import Settings, get_settings
from analytica_api.persistence.database import Database
from analytica_api.persistence.unit_of_work import SqlAlchemyUnitOfWork
from analytica_api.queue.contracts import JobQueue
from analytica_api.queue.providers import InlineJobQueue, VercelJobQueue
from analytica_api.services.analyze import DatasetAnalyzeService
from analytica_api.services.control_plane import ControlPlaneService
from analytica_api.services.explore import DatasetExploreService
from analytica_api.services.ingestion import DatasetIngestionService
from analytica_api.services.ingestion_worker import IngestionWorker
from analytica_api.services.preview import DatasetPreviewService
from analytica_api.services.profile import DatasetProfileService
from analytica_api.services.transform import DatasetTransformService
from analytica_api.services.transform_worker import TransformWorker
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
def get_ingestion_worker() -> IngestionWorker:
    return IngestionWorker(
        settings=get_settings(),
        control_plane=get_control_plane(),
        store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_transform_worker() -> TransformWorker:
    return TransformWorker(
        control_plane=get_control_plane(),
        store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_job_queue() -> JobQueue:
    settings: Settings = get_settings()
    if settings.queue_provider == "vercel":
        return VercelJobQueue()
    return InlineJobQueue(
        get_ingestion_worker().run,
        get_transform_worker().run,
    )


@lru_cache(maxsize=1)
def get_ingestion_service() -> DatasetIngestionService:
    return DatasetIngestionService(
        settings=get_settings(),
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
        job_queue=get_job_queue(),
    )


@lru_cache(maxsize=1)
def get_transform_service() -> DatasetTransformService:
    return DatasetTransformService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
        job_queue=get_job_queue(),
    )


@lru_cache(maxsize=1)
def get_preview_service() -> DatasetPreviewService:
    return DatasetPreviewService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_profile_service() -> DatasetProfileService:
    return DatasetProfileService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_explore_service() -> DatasetExploreService:
    return DatasetExploreService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
    )


@lru_cache(maxsize=1)
def get_analyze_service() -> DatasetAnalyzeService:
    return DatasetAnalyzeService(
        control_plane=get_control_plane(),
        artifact_store=get_artifact_store(),
    )

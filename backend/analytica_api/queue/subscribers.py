import asyncio
from uuid import UUID

from vercel.queue import Message, subscribe

from analytica_api.queue.providers import (
    EXPORT_TOPIC,
    INGESTION_TOPIC,
    MODEL_TOPIC,
    TRANSFORM_TOPIC,
)
from analytica_api.runtime import (
    get_export_worker,
    get_ingestion_worker,
    get_model_worker,
    get_transform_worker,
)


@subscribe(topic=INGESTION_TOPIC, retry_after=60, max_attempts=5)
async def ingest_dataset(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_ingestion_worker().run, job_id)


@subscribe(topic=TRANSFORM_TOPIC, retry_after=60, max_attempts=5)
async def transform_dataset(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_transform_worker().run, job_id)


@subscribe(topic=MODEL_TOPIC, retry_after=60, max_attempts=5)
async def train_model(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_model_worker().run, job_id)


@subscribe(topic=EXPORT_TOPIC, retry_after=60, max_attempts=5)
async def export_results(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_export_worker().run, job_id)

import asyncio
from uuid import UUID

from vercel.queue import Message, subscribe

from analytica_api.queue.providers import INGESTION_TOPIC, TRANSFORM_TOPIC
from analytica_api.runtime import get_ingestion_worker, get_transform_worker


@subscribe(topic=INGESTION_TOPIC, retry_after=60, max_attempts=5)
async def ingest_dataset(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_ingestion_worker().run, job_id)


@subscribe(topic=TRANSFORM_TOPIC, retry_after=60, max_attempts=5)
async def transform_dataset(message: Message[dict[str, str]]) -> None:
    job_id = UUID(message.payload["job_id"])
    await asyncio.to_thread(get_transform_worker().run, job_id)

import asyncio
from uuid import UUID

from vercel.queue import subscribe

from analytica_api.queue.providers import INGESTION_TOPIC
from analytica_api.runtime import get_ingestion_worker


@subscribe(topic=INGESTION_TOPIC)
async def ingest_dataset(message: dict[str, str]) -> None:
    job_id = UUID(message["job_id"])
    await asyncio.to_thread(get_ingestion_worker().run, job_id)

import asyncio
from collections.abc import Callable
from uuid import UUID

from vercel.queue import send

INGESTION_TOPIC = "dataset-ingestion"


class VercelJobQueue:
    async def publish_ingestion(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None:
        message_id = await send(
            INGESTION_TOPIC,
            {"job_id": str(job_id)},
            idempotency_key=idempotency_key,
        )
        return str(message_id) if message_id is not None else None


class InlineJobQueue:
    """Development/test queue preserving the asynchronous publisher contract."""

    def __init__(self, handler: Callable[[UUID], None]):
        self.handler = handler

    async def publish_ingestion(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None:
        del idempotency_key
        await asyncio.to_thread(self.handler, job_id)
        return None

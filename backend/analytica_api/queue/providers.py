import asyncio
from collections.abc import Callable
from uuid import UUID

from vercel.queue import send

INGESTION_TOPIC = "dataset-ingestion"
TRANSFORM_TOPIC = "dataset-transform"


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

    async def publish_transform(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None:
        message_id = await send(
            TRANSFORM_TOPIC,
            {"job_id": str(job_id)},
            idempotency_key=idempotency_key,
        )
        return str(message_id) if message_id is not None else None


class InlineJobQueue:
    """Development/test queue preserving the asynchronous publisher contract."""

    def __init__(
        self,
        ingestion_handler: Callable[[UUID], None],
        transform_handler: Callable[[UUID], None] | None = None,
    ):
        self.ingestion_handler = ingestion_handler
        self.transform_handler = transform_handler

    async def publish_ingestion(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None:
        del idempotency_key
        await asyncio.to_thread(self.ingestion_handler, job_id)
        return None

    async def publish_transform(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None:
        del idempotency_key
        if self.transform_handler is None:
            raise RuntimeError("inline transform handler is not configured")
        await asyncio.to_thread(self.transform_handler, job_id)
        return None

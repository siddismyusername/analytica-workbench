from typing import Protocol
from uuid import UUID


class JobQueue(Protocol):
    async def publish_ingestion(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None: ...

    async def publish_transform(
        self,
        job_id: UUID,
        *,
        idempotency_key: str,
    ) -> str | None: ...

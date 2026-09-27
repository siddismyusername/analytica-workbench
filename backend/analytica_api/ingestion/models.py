from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from analytica_api.domain.datasets import DatasetSchema

SourceFormat = Literal["csv", "parquet"]


class IngestionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_format: SourceFormat
    canonical_format: Literal["parquet"] = "parquet"
    row_count: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    schema: DatasetSchema

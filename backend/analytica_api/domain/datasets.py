from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DataType = Literal[
    "boolean",
    "integer",
    "float",
    "string",
    "date",
    "datetime",
    "categorical",
    "unknown",
]


class DatasetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    column_id: str = Field(min_length=1)
    physical_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    data_type: DataType
    storage_type: str | None = None
    nullable: bool = True


class DatasetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    columns: tuple[DatasetColumn, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_columns(self) -> "DatasetSchema":
        ids = [column.column_id for column in self.columns]
        names = [column.physical_name for column in self.columns]
        if len(ids) != len(set(ids)):
            raise ValueError("column_id values must be unique")
        if len(names) != len(set(names)):
            raise ValueError("physical_name values must be unique")
        return self

    def by_id(self) -> dict[str, DatasetColumn]:
        return {column.column_id: column for column in self.columns}


class DatasetSource(BaseModel):
    """Internal reference to an immutable canonical dataset object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["parquet"] = "parquet"
    uri: str = Field(min_length=1)

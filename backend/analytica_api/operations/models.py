from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

JsonScalar = StrictBool | StrictInt | StrictFloat | StrictStr
FilterOperator = Literal["eq", "neq", "gt", "gte", "lt", "lte", "is_null", "not_null"]


class OperationBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    version: Literal[1] = 1


class FilterOperation(OperationBase):
    type: Literal["filter"] = "filter"
    column_id: str = Field(min_length=1)
    operator: FilterOperator
    value: JsonScalar | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "FilterOperation":
        null_operator = self.operator in {"is_null", "not_null"}
        if null_operator and self.value is not None:
            raise ValueError(f"{self.operator} does not accept a value")
        if not null_operator and self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        return self


class DropColumnsOperation(OperationBase):
    type: Literal["drop_columns"] = "drop_columns"
    column_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_columns(self) -> "DropColumnsOperation":
        if len(self.column_ids) != len(set(self.column_ids)):
            raise ValueError("column_ids must be unique")
        return self


class FillNullOperation(OperationBase):
    type: Literal["fill_null"] = "fill_null"
    column_id: str = Field(min_length=1)
    strategy: Literal["constant"] = "constant"
    value: JsonScalar


class DeduplicateOperation(OperationBase):
    type: Literal["deduplicate"] = "deduplicate"


Operation = Annotated[
    FilterOperation | DropColumnsOperation | FillNullOperation | DeduplicateOperation,
    Field(discriminator="type"),
]


class PipelineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    operations: tuple[Operation, ...] = ()

    @model_validator(mode="after")
    def validate_unique_operation_ids(self) -> "PipelineSpec":
        ids = [operation.operation_id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("operation_id values must be unique")
        return self

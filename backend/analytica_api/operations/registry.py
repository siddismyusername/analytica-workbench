from typing import Literal

from pydantic import BaseModel, ConfigDict

ExecutionClass = Literal["interactive", "deferred"]


class OperationDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    version: int
    label: str
    description: str
    execution_class: ExecutionClass


_OPERATION_CATALOG = (
    OperationDescriptor(
        type="filter",
        version=1,
        label="Filter rows",
        description="Keep rows that satisfy a typed comparison against one column.",
        execution_class="interactive",
    ),
    OperationDescriptor(
        type="drop_columns",
        version=1,
        label="Drop columns",
        description="Remove one or more columns from the active dataset view.",
        execution_class="interactive",
    ),
    OperationDescriptor(
        type="fill_null",
        version=1,
        label="Fill missing values",
        description="Replace null values in one column with a constant value.",
        execution_class="interactive",
    ),
    OperationDescriptor(
        type="deduplicate",
        version=1,
        label="Remove duplicate rows",
        description="Keep one copy of each distinct row after prior pipeline operations.",
        execution_class="interactive",
    ),
    OperationDescriptor(
        type="rename_column",
        version=1,
        label="Rename column",
        description="Rename one column while preserving its stable internal identifier.",
        execution_class="interactive",
    ),
    OperationDescriptor(
        type="cast_column",
        version=1,
        label="Change column type",
        description="Convert one column to a supported analytical data type.",
        execution_class="interactive",
    ),
)


def operation_catalog() -> tuple[OperationDescriptor, ...]:
    return _OPERATION_CATALOG

import { backendBaseUrl, errorText } from "@/lib/dataset-upload";

export type Scalar = string | number | boolean;

export type FilterOperator =
  | "eq"
  | "neq"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "is_null"
  | "not_null";

export type PrepareOperation =
  | {
      operation_id: string;
      version: 1;
      type: "filter";
      column_id: string;
      operator: FilterOperator;
      value: Scalar | null;
    }
  | {
      operation_id: string;
      version: 1;
      type: "drop_columns";
      column_ids: string[];
    }
  | {
      operation_id: string;
      version: 1;
      type: "fill_null";
      column_id: string;
      strategy: "constant";
      value: Scalar;
    }
  | {
      operation_id: string;
      version: 1;
      type: "deduplicate";
    }
  | {
      operation_id: string;
      version: 1;
      type: "rename_column";
      column_id: string;
      new_name: string;
    }
  | {
      operation_id: string;
      version: 1;
      type: "cast_column";
      column_id: string;
      target_type: "boolean" | "integer" | "float" | "string" | "date" | "datetime";
    };

export type TransformPreview = {
  input_version_id: string;
  columns: string[];
  rows: unknown[][];
  input_row_count: number;
  output_row_count: number;
  output_schema: {
    schema_version: number;
    columns: Array<{
      column_id: string;
      physical_name: string;
      display_name: string;
      data_type: string;
      storage_type: string | null;
      nullable: boolean;
    }>;
  };
};

export type TransformJob = {
  job_id: string;
  input_version_id: string;
  version_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  error_detail: { type?: string; message?: string } | null;
};

export type TransformHistoryItem = {
  job_id: string;
  input_version_id: string;
  output_version_id: string;
  output_version_number: number;
  operation: PrepareOperation;
  created_at: string;
};

export async function previewTransform(
  versionId: string,
  operation: PrepareOperation,
  limit = 50,
): Promise<TransformPreview> {
  const query = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/transforms/preview?${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not preview transformation: ${await errorText(response)}`);
  }
  return (await response.json()) as TransformPreview;
}

export async function applyTransform(
  versionId: string,
  operation: PrepareOperation,
): Promise<TransformJob> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/transforms`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not apply transformation: ${await errorText(response)}`);
  }
  return (await response.json()) as TransformJob;
}

export async function getTransformStatus(jobId: string): Promise<TransformJob> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/transforms/${encodeURIComponent(jobId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not read transformation status: ${await errorText(response)}`);
  }
  return (await response.json()) as TransformJob;
}

export async function getTransformHistory(versionId: string): Promise<TransformHistoryItem[]> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/history`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not read operation history: ${await errorText(response)}`);
  }
  return (await response.json()) as TransformHistoryItem[];
}

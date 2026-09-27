import type { PutBlobResult } from "@vercel/blob";
import { upload } from "@vercel/blob/client";

export type DatasetUploadProgress = {
  loaded: number;
  total: number;
  percentage: number;
};

export type DatasetIngestion = {
  job_id: string;
  dataset_id: string;
  version_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
};

function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_ANALYTICA_API_URL?.replace(/\/$/, "");
  if (configured) return configured;
  if (process.env.NODE_ENV !== "production") return "http://localhost:8000";
  throw new Error("NEXT_PUBLIC_ANALYTICA_API_URL is required in production");
}

function sourceFormat(filename: string): "csv" | "parquet" {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".csv")) return "csv";
  if (lower.endsWith(".parquet")) return "parquet";
  throw new Error("Only CSV and Parquet datasets are supported");
}

async function responseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string; detail?: string };
    return body.error ?? body.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function uploadDataset(
  file: File,
  onProgress?: (progress: DatasetUploadProgress) => void,
): Promise<PutBlobResult> {
  const format = sourceFormat(file.name);
  return upload(`datasets/source/${format}/${file.name}`, file, {
    access: "private",
    handleUploadUrl: "/api/uploads",
    multipart: true,
    onUploadProgress: onProgress,
  });
}

export async function uploadAndIngestDataset(
  file: File,
  datasetName: string,
  onProgress?: (progress: DatasetUploadProgress) => void,
): Promise<DatasetIngestion> {
  const name = datasetName.trim();
  if (!name) throw new Error("Dataset name is required");
  if (file.size <= 0) throw new Error("Dataset file is empty");

  const blob = await uploadDataset(file, onProgress);
  const response = await fetch(`${apiBaseUrl()}/api/v1/datasets/ingestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      source_key: blob.pathname,
    }),
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return (await response.json()) as DatasetIngestion;
}

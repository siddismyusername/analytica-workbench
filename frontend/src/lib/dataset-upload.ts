export type DatasetIngestion = {
  job_id: string;
  dataset_id: string;
  version_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
};

type PresignedUpload = {
  pathname: string;
  presignedUrl: string;
  expiresAt: string;
  sourceFormat: "csv" | "parquet";
  contentType: string;
};

function backendBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_ANALYTICA_API_URL?.trim();
  if (!value) {
    throw new Error("NEXT_PUBLIC_ANALYTICA_API_URL is not configured");
  }
  return value.replace(/\/$/, "");
}

async function errorText(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string; detail?: string };
    return payload.error ?? payload.detail ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

export async function uploadDataset(
  file: File,
  datasetName: string,
): Promise<DatasetIngestion> {
  const presignResponse = await fetch("/api/uploads/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      contentType: file.type || undefined,
      size: file.size,
    }),
  });
  if (!presignResponse.ok) {
    throw new Error(`Could not authorize upload: ${await errorText(presignResponse)}`);
  }
  const presigned = (await presignResponse.json()) as PresignedUpload;

  const uploadResponse = await fetch(presigned.presignedUrl, {
    method: "PUT",
    headers: { "Content-Type": presigned.contentType },
    body: file,
  });
  if (!uploadResponse.ok) {
    throw new Error(`Object upload failed: HTTP ${uploadResponse.status}`);
  }

  const ingestionResponse = await fetch(`${backendBaseUrl()}/api/v1/datasets/ingestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: datasetName,
      source_key: presigned.pathname,
      source_format: presigned.sourceFormat,
      idempotency_key: `upload:${crypto.randomUUID()}`,
    }),
  });
  if (!ingestionResponse.ok) {
    throw new Error(`Could not start ingestion: ${await errorText(ingestionResponse)}`);
  }
  return (await ingestionResponse.json()) as DatasetIngestion;
}

export async function getIngestionStatus(jobId: string): Promise<DatasetIngestion> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/ingestions/${encodeURIComponent(jobId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not read ingestion status: ${await errorText(response)}`);
  }
  return (await response.json()) as DatasetIngestion;
}

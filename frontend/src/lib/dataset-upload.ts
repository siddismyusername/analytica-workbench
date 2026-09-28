export type DatasetIngestion = {
  job_id: string;
  dataset_id: string;
  version_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
};

export type DatasetColumnProfile = {
  column_id: string;
  name: string;
  display_name: string;
  data_type: string;
  storage_type: string | null;
  nullable: boolean;
  null_count: number;
  null_percentage: number;
  distinct_count: number;
};

export type DatasetProfile = {
  version_id: string;
  dataset_id: string;
  dataset_name: string;
  version_number: number;
  row_count: number;
  column_count: number;
  byte_size: number;
  missing_cells: number;
  missing_percentage: number;
  duplicate_rows: number;
  duplicate_percentage: number;
  columns: DatasetColumnProfile[];
  warnings: Array<{
    code: string;
    severity: string;
    message: string;
  }>;
};

export type DatasetPreview = {
  version_id: string;
  columns: string[];
  rows: unknown[][];
  offset: number;
  limit: number;
};

type PresignedUpload = {
  pathname: string;
  presignedUrl: string;
  expiresAt: string | null;
  contentType: string;
};

export function backendBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_ANALYTICA_API_URL?.trim();
  if (!value) {
    throw new Error("NEXT_PUBLIC_ANALYTICA_API_URL is not configured");
  }
  return value.replace(/\/$/, "");
}

export async function errorText(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string; detail?: string };
    return payload.error ?? payload.detail ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

function putFileWithProgress(
  url: string,
  contentType: string,
  file: File,
  onProgress?: (percentage: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    request.setRequestHeader("Content-Type", contentType);
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    };
    request.onerror = () => reject(new Error("Object upload failed due to a network error"));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress?.(100);
        resolve();
        return;
      }
      reject(new Error(`Object upload failed: HTTP ${request.status}`));
    };
    request.send(file);
  });
}

export async function uploadDataset(
  file: File,
  datasetName: string,
  onProgress?: (percentage: number) => void,
): Promise<DatasetIngestion> {
  const presignResponse = await fetch("/api/uploads/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, size: file.size }),
  });
  if (!presignResponse.ok) {
    throw new Error(`Could not authorize upload: ${await errorText(presignResponse)}`);
  }
  const presigned = (await presignResponse.json()) as PresignedUpload;
  await putFileWithProgress(presigned.presignedUrl, presigned.contentType, file, onProgress);

  const ingestionResponse = await fetch(`${backendBaseUrl()}/api/v1/datasets/ingestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: datasetName, source_key: presigned.pathname }),
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

export async function getDatasetProfile(versionId: string): Promise<DatasetProfile> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/profile`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not profile dataset: ${await errorText(response)}`);
  }
  return (await response.json()) as DatasetProfile;
}

export async function getDatasetPreview(
  versionId: string,
  offset = 0,
  limit = 200,
): Promise<DatasetPreview> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/preview?${query}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not preview dataset: ${await errorText(response)}`);
  }
  return (await response.json()) as DatasetPreview;
}

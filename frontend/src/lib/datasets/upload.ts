export type DatasetUploadResult = {
  dataset_id: string;
  job_id: string;
  job_status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  output_version_id: string | null;
};

type PresignResponse = {
  uploadUrl: string;
  storageKey: string;
  contentType: string;
  expiresAt: string;
};

function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_ANALYTICA_API_URL?.replace(/\/$/, "");
  if (configured) return configured;
  if (process.env.NODE_ENV !== "production") return "http://localhost:8000";
  throw new Error("NEXT_PUBLIC_ANALYTICA_API_URL is required in production");
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string; detail?: string };
    return payload.error ?? payload.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function uploadDatasetFile(
  file: File,
  datasetName: string,
): Promise<DatasetUploadResult> {
  const name = datasetName.trim();
  if (!name) throw new Error("Dataset name is required");
  if (file.size <= 0) throw new Error("Dataset file is empty");

  const presignResponse = await fetch("/api/uploads/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, size: file.size }),
  });
  if (!presignResponse.ok) {
    throw new Error(await errorMessage(presignResponse));
  }
  const presign = (await presignResponse.json()) as PresignResponse;

  const uploadResponse = await fetch(presign.uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": presign.contentType },
    body: file,
  });
  if (!uploadResponse.ok) {
    throw new Error(`Dataset upload failed (${uploadResponse.status})`);
  }

  const completionResponse = await fetch(
    `${apiBaseUrl()}/api/v1/datasets/uploads/complete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_name: name,
        storage_key: presign.storageKey,
      }),
    },
  );
  if (!completionResponse.ok) {
    throw new Error(await errorMessage(completionResponse));
  }

  return (await completionResponse.json()) as DatasetUploadResult;
}

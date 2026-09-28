import { backendBaseUrl, errorText } from "@/lib/dataset-upload";

export type SavedResult = {
  id: string;
  dataset_version_id: string;
  source_job_id: string | null;
  kind: "analysis" | "chart" | "model";
  title: string;
  fingerprint: string;
  configuration: Record<string, unknown>;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ExportKind = "dataset_csv" | "dataset_parquet" | "report_html" | "chart_svg";
export type ExportJob = {
  job_id: string | null;
  version_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  kind: ExportKind;
  artifact_id: string | null;
  error_detail: { message?: string } | null;
  title: string | null;
  created_at: string;
};

export function artifactDownloadUrl(artifactId: string): string {
  return `${backendBaseUrl()}/api/v1/artifacts/${encodeURIComponent(artifactId)}/download`;
}

export async function getSavedResults(versionId: string): Promise<SavedResult[]> {
  const response = await fetch(`${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/results`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load saved results: ${await errorText(response)}`);
  return (await response.json()) as SavedResult[];
}

export async function getExports(versionId: string): Promise<ExportJob[]> {
  const response = await fetch(`${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/exports`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load exports: ${await errorText(response)}`);
  return (await response.json()) as ExportJob[];
}

export async function getExport(jobId: string): Promise<ExportJob> {
  const response = await fetch(`${backendBaseUrl()}/api/v1/exports/${encodeURIComponent(jobId)}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load export: ${await errorText(response)}`);
  return (await response.json()) as ExportJob;
}

export async function createExport(versionId: string, kind: ExportKind, title = "", resultIds: string[] = []): Promise<ExportJob> {
  const response = await fetch(`${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, title, result_ids: resultIds }),
  });
  if (!response.ok) throw new Error(`Could not create export: ${await errorText(response)}`);
  return (await response.json()) as ExportJob;
}

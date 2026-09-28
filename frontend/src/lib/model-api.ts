import { backendBaseUrl, errorText } from "@/lib/dataset-upload";

export type ProblemType = "regression" | "classification";
export type Algorithm = "linear" | "decision_tree" | "random_forest";

export type ModelRunConfig = {
  problem_type: ProblemType;
  target_column_id: string;
  feature_column_ids: string[];
  algorithms: Algorithm[];
  test_fraction: number;
  random_seed: number;
  cross_validation: boolean;
};

export type ModelCandidate = {
  algorithm: Algorithm | "baseline";
  metrics: Record<string, number | string[] | number[][]>;
  cv_score: number | null;
  validation_score: number;
};

export type ModelResult = {
  version_id: string;
  configuration: ModelRunConfig;
  train_rows: number;
  test_rows: number;
  excluded_target_rows: number;
  primary_metric: "rmse" | "macro_f1";
  validation_method: string;
  candidates: ModelCandidate[];
  best_algorithm: Algorithm;
  explanation: Array<{ feature: string; value: number }>;
  explanation_note: string;
};

export type ModelRun = {
  job_id: string;
  version_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  configuration: ModelRunConfig;
  error_detail: { message?: string } | null;
  result: ModelResult | null;
  artifacts: Record<string, string>;
};

export async function submitModelRun(versionId: string, config: ModelRunConfig): Promise<ModelRun> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/models/runs`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) },
  );
  if (!response.ok) throw new Error(`Could not start model run: ${await errorText(response)}`);
  return (await response.json()) as ModelRun;
}

export async function getModelRuns(versionId: string): Promise<ModelRun[]> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/models/runs`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`Could not load model runs: ${await errorText(response)}`);
  return (await response.json()) as ModelRun[];
}

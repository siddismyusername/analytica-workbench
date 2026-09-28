import { backendBaseUrl, errorText } from "@/lib/dataset-upload";
import type { ExploreChartType, VisualizationResult } from "@/lib/explore-api";

export type AnalysisGoal =
  | "compare_groups"
  | "compare_paired"
  | "numeric_relationship"
  | "categorical_association"
  | "one_sample";

export type AnalysisTestId =
  | "welch_t"
  | "paired_t"
  | "one_sample_t"
  | "welch_anova"
  | "mann_whitney"
  | "wilcoxon"
  | "kruskal"
  | "chi_square"
  | "pearson"
  | "spearman";

export type AnalysisAlternative = "two-sided" | "less" | "greater";

export type Recommendation = {
  test_id: AnalysisTestId;
  name: string;
  preferred: boolean;
  rationale: string;
  assumptions: string[];
};

export type RecommendationResult = {
  version_id: string;
  goal: AnalysisGoal;
  recommendations: Recommendation[];
  notes: string[];
};

export type AnalysisResult = {
  version_id: string;
  test_id: AnalysisTestId;
  test_name: string;
  null_hypothesis: string;
  alternative: AnalysisAlternative;
  alpha: number;
  sample_size: number;
  estimate: { name: string; value: number } | null;
  confidence_interval: {
    level: number;
    low: number | null;
    high: number | null;
    label: string;
  } | null;
  statistic: {
    name: string;
    value: number;
    degrees_of_freedom: number | null;
  };
  p_value: number;
  significant: boolean;
  effect_size: {
    name: string;
    value: number;
    magnitude: string | null;
  } | null;
  group_summaries: Array<{
    label: string;
    n: number;
    mean: number | null;
    median: number | null;
    stddev: number | null;
  }>;
  diagnostics: Array<{
    name: string;
    statistic: number | null;
    p_value: number | null;
    status: "pass" | "warning" | "info" | "unavailable";
    sample_size: number | null;
    message: string;
  }>;
  visualizations: Array<Omit<VisualizationResult, "version_id"> & { chart_type: ExploreChartType }>;
  warnings: string[];
  interpretation: string;
};

export async function getAnalysisRecommendations(
  versionId: string,
  payload: {
    goal: AnalysisGoal;
    outcomeColumnId?: string | null;
    groupColumnId?: string | null;
    secondaryColumnId?: string | null;
  },
): Promise<RecommendationResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/analyze/recommendations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: payload.goal,
        outcome_column_id: payload.outcomeColumnId ?? null,
        group_column_id: payload.groupColumnId ?? null,
        secondary_column_id: payload.secondaryColumnId ?? null,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not recommend a statistical test: ${await errorText(response)}`);
  }
  return (await response.json()) as RecommendationResult;
}

export async function runAnalysis(
  versionId: string,
  payload: {
    testId: AnalysisTestId;
    xColumnId: string;
    yColumnId?: string | null;
    groupColumnId?: string | null;
    referenceValue?: number | null;
    confidenceLevel?: number;
    alternative?: AnalysisAlternative;
  },
): Promise<AnalysisResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/analyze/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        test_id: payload.testId,
        x_column_id: payload.xColumnId,
        y_column_id: payload.yColumnId ?? null,
        group_column_id: payload.groupColumnId ?? null,
        reference_value: payload.referenceValue ?? null,
        confidence_level: payload.confidenceLevel ?? 0.95,
        alternative: payload.alternative ?? "two-sided",
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not run statistical analysis: ${await errorText(response)}`);
  }
  return (await response.json()) as AnalysisResult;
}

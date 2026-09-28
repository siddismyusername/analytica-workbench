import { backendBaseUrl, errorText } from "@/lib/dataset-upload";

export type JsonScalar = string | number | boolean | null;

export type DescriptiveResult = {
  version_id: string;
  column_id: string;
  column_name: string;
  data_type: string;
  row_count: number;
  valid_count: number;
  missing_count: number;
  distinct_count: number;
  minimum: JsonScalar;
  maximum: JsonScalar;
  mean: number | null;
  stddev: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  mode: JsonScalar;
  mode_count: number;
};

export type FrequencyItem = {
  value: JsonScalar;
  count: number;
  percentage: number;
};

export type FrequencyResult = {
  version_id: string;
  column_id: string;
  column_name: string;
  total_rows: number;
  truncated: boolean;
  items: FrequencyItem[];
};

export type CorrelationColumn = {
  column_id: string;
  name: string;
};

export type CorrelationResult = {
  version_id: string;
  method: "pearson";
  columns: CorrelationColumn[];
  matrix: Array<Array<number | null>>;
};

export type CrosstabResult = {
  version_id: string;
  row_column: CorrelationColumn;
  column_column: CorrelationColumn;
  row_values: JsonScalar[];
  column_values: JsonScalar[];
  counts: number[][];
  row_totals: number[];
  column_totals: number[];
  total: number;
};

export type ExploreChartType =
  | "histogram"
  | "bar"
  | "line"
  | "scatter"
  | "box"
  | "heatmap"
  | "qq";

export type VisualizationResult = {
  version_id: string;
  chart_type: ExploreChartType;
  title: string;
  x_label: string | null;
  y_label: string | null;
  data: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
};

export async function getDescriptives(
  versionId: string,
  columnId: string,
): Promise<DescriptiveResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/explore/descriptives/${encodeURIComponent(columnId)}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not calculate descriptive statistics: ${await errorText(response)}`);
  }
  return (await response.json()) as DescriptiveResult;
}

export async function getFrequencies(
  versionId: string,
  columnId: string,
  limit = 30,
): Promise<FrequencyResult> {
  const query = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/explore/frequencies/${encodeURIComponent(columnId)}?${query}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Could not calculate frequencies: ${await errorText(response)}`);
  }
  return (await response.json()) as FrequencyResult;
}

export async function getCorrelations(
  versionId: string,
  columnIds?: string[],
): Promise<CorrelationResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/explore/correlations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ column_ids: columnIds?.length ? columnIds : null }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not calculate correlations: ${await errorText(response)}`);
  }
  return (await response.json()) as CorrelationResult;
}

export async function getCrosstab(
  versionId: string,
  rowColumnId: string,
  columnColumnId: string,
  limit = 12,
): Promise<CrosstabResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/explore/crosstab`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        row_column_id: rowColumnId,
        column_column_id: columnColumnId,
        limit,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not calculate crosstab: ${await errorText(response)}`);
  }
  return (await response.json()) as CrosstabResult;
}

export async function getVisualization(
  versionId: string,
  chartType: ExploreChartType,
  xColumnId: string,
  options: {
    yColumnId?: string | null;
    bins?: number;
    limit?: number;
  } = {},
): Promise<VisualizationResult> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/datasets/versions/${encodeURIComponent(versionId)}/explore/visualizations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chart_type: chartType,
        x_column_id: xColumnId,
        y_column_id: options.yColumnId ?? null,
        bins: options.bins ?? 20,
        limit: options.limit ?? 1000,
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`Could not build visualization: ${await errorText(response)}`);
  }
  return (await response.json()) as VisualizationResult;
}

"use client";

import { useEffect, useMemo, useState } from "react";

import { ExploreChart } from "@/components/explore-chart";
import styles from "./explore-workspace.module.css";
import type { DatasetColumnProfile, DatasetProfile } from "@/lib/dataset-upload";
import {
  type CorrelationResult,
  type CrosstabResult,
  type DescriptiveResult,
  type ExploreChartType,
  type FrequencyResult,
  type VisualizationResult,
  getCorrelations,
  getCrosstab,
  getDescriptives,
  getFrequencies,
  getVisualization,
} from "@/lib/explore-api";

type ExplorePanel = "column" | "correlation" | "crosstab" | "visualize";

const NUMERIC_TYPES = new Set(["integer", "float"]);
const TEMPORAL_TYPES = new Set(["date", "datetime"]);
const CATEGORICAL_TYPES = new Set(["boolean", "string", "categorical"]);
const CHARTS: Array<{
  type: ExploreChartType;
  label: string;
  description: string;
}> = [
  { type: "histogram", label: "Histogram", description: "Numeric distribution" },
  { type: "bar", label: "Bar", description: "Category frequency" },
  { type: "line", label: "Line", description: "Ordered relationship" },
  { type: "scatter", label: "Scatter", description: "Numeric relationship" },
  { type: "box", label: "Box", description: "Spread and quartiles" },
  { type: "heatmap", label: "Heatmap", description: "Correlation matrix" },
  { type: "qq", label: "Q-Q", description: "Normality diagnostic" },
];

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Missing";
  if (typeof value === "number") {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
  }
  return String(value);
}

function metricValue(value: number | null): string {
  return value === null
    ? "—"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
}

function chartSupported(
  chart: ExploreChartType,
  x: DatasetColumnProfile,
  y: DatasetColumnProfile | null,
): boolean {
  const xNumeric = NUMERIC_TYPES.has(x.data_type);
  const yNumeric = y ? NUMERIC_TYPES.has(y.data_type) : false;
  if (chart === "heatmap") return true;
  if (chart === "histogram" || chart === "qq") return xNumeric;
  if (chart === "bar") return true;
  if (chart === "box") return xNumeric;
  if (chart === "scatter") return xNumeric && yNumeric;
  return (xNumeric || TEMPORAL_TYPES.has(x.data_type)) && yNumeric;
}

export function ExploreWorkspace({ profile }: { profile: DatasetProfile }) {
  const [panel, setPanel] = useState<ExplorePanel>("column");
  const [selectedColumnId, setSelectedColumnId] = useState(
    profile.columns[0]?.column_id ?? "",
  );
  const [secondaryColumnId, setSecondaryColumnId] = useState(
    profile.columns[1]?.column_id ?? profile.columns[0]?.column_id ?? "",
  );
  const [crosstabRowId, setCrosstabRowId] = useState(
    profile.columns.find((column) => CATEGORICAL_TYPES.has(column.data_type))?.column_id ?? "",
  );
  const [crosstabColumnId, setCrosstabColumnId] = useState(
    profile.columns.filter((column) => CATEGORICAL_TYPES.has(column.data_type))[1]?.column_id ?? "",
  );
  const [descriptives, setDescriptives] = useState<DescriptiveResult | null>(null);
  const [frequencies, setFrequencies] = useState<FrequencyResult | null>(null);
  const [correlations, setCorrelations] = useState<CorrelationResult | null>(null);
  const [crosstab, setCrosstab] = useState<CrosstabResult | null>(null);
  const [chartType, setChartType] = useState<ExploreChartType>("histogram");
  const [visualization, setVisualization] = useState<VisualizationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedColumn = useMemo(
    () =>
      profile.columns.find((column) => column.column_id === selectedColumnId) ??
      profile.columns[0] ??
      null,
    [profile.columns, selectedColumnId],
  );
  const secondaryColumn = useMemo(
    () =>
      profile.columns.find((column) => column.column_id === secondaryColumnId) ??
      profile.columns.find((column) => column.column_id !== selectedColumn?.column_id) ??
      null,
    [profile.columns, secondaryColumnId, selectedColumn?.column_id],
  );
  const numericColumns = useMemo(
    () => profile.columns.filter((column) => NUMERIC_TYPES.has(column.data_type)),
    [profile.columns],
  );
  const categoricalColumns = useMemo(
    () => profile.columns.filter((column) => CATEGORICAL_TYPES.has(column.data_type)),
    [profile.columns],
  );
  const activeColumnId = selectedColumn?.column_id ?? "";

  useEffect(() => {
    if (!activeColumnId) return;
    let cancelled = false;
    void Promise.all([
      getDescriptives(profile.version_id, activeColumnId),
      getFrequencies(profile.version_id, activeColumnId, 30),
    ])
      .then(([nextDescriptives, nextFrequencies]) => {
        if (cancelled) return;
        setDescriptives(nextDescriptives);
        setFrequencies(nextFrequencies);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not explore this column.");
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profile.version_id, activeColumnId]);

  async function loadCorrelations() {
    setPanel("correlation");
    if (correlations?.version_id === profile.version_id) return;
    setBusy(true);
    setError(null);
    try {
      setCorrelations(await getCorrelations(profile.version_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not calculate correlations.");
    } finally {
      setBusy(false);
    }
  }

  async function loadCrosstab() {
    if (!crosstabRowId || !crosstabColumnId) return;
    if (crosstabRowId === crosstabColumnId) {
      setError("Choose two different columns for a crosstab.");
      return;
    }
    setPanel("crosstab");
    setBusy(true);
    setError(null);
    setCrosstab(null);
    try {
      setCrosstab(
        await getCrosstab(
          profile.version_id,
          crosstabRowId,
          crosstabColumnId,
          12,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not calculate crosstab.");
    } finally {
      setBusy(false);
    }
  }

  async function buildVisualization(nextType: ExploreChartType = chartType) {
    if (!selectedColumn) return;
    const needsY = nextType === "line" || nextType === "scatter";
    if (needsY && !secondaryColumn) {
      setError("Choose a second column for this chart.");
      return;
    }
    setPanel("visualize");
    setChartType(nextType);
    setBusy(true);
    setError(null);
    try {
      setVisualization(
        await getVisualization(profile.version_id, nextType, selectedColumn.column_id, {
          yColumnId: nextType === "box" || needsY ? secondaryColumn?.column_id : null,
          bins: 20,
          limit: nextType === "scatter" || nextType === "qq" ? 3000 : 1000,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not build visualization.");
    } finally {
      setBusy(false);
    }
  }

  function selectColumn(column: DatasetColumnProfile) {
    setBusy(true);
    setError(null);
    setDescriptives(null);
    setFrequencies(null);
    setSelectedColumnId(column.column_id);
    setPanel("column");
    setVisualization(null);
    setChartType(NUMERIC_TYPES.has(column.data_type) ? "histogram" : "bar");
  }

  if (!selectedColumn) {
    return <div className={styles.empty}>This dataset has no columns to explore.</div>;
  }

  return (
    <section className={styles.layout} aria-label="Explore workspace">
      <aside className={styles.columnRail}>
        <div className={styles.railHeading}>
          <div>
            <p className="eyebrow">Explore</p>
            <h2>Variables</h2>
          </div>
          <span>{profile.column_count} columns</span>
        </div>
        <div className={styles.columnList}>
          {profile.columns.map((column) => (
            <button
              type="button"
              className={`${styles.columnButton} ${
                selectedColumn.column_id === column.column_id ? styles.columnButtonActive : ""
              }`}
              key={column.column_id}
              onClick={() => selectColumn(column)}
            >
              <div>
                <strong>{column.display_name}</strong>
                <span>{column.data_type}</span>
              </div>
              <small>
                {column.distinct_count.toLocaleString()} distinct ·{" "}
                {column.null_percentage.toFixed(1)}% missing
              </small>
            </button>
          ))}
        </div>
      </aside>

      <section className={styles.canvas}>
        <header className={styles.canvasHeader}>
          <div>
            <p className="eyebrow">Immutable version {profile.version_number}</p>
            <h2>{selectedColumn.display_name}</h2>
            <p>Explore distributions and relationships without changing the dataset.</p>
          </div>
          <div className={styles.modeTabs} role="tablist" aria-label="Explore views">
            <button
              className={panel === "column" ? styles.modeActive : ""}
              type="button"
              onClick={() => setPanel("column")}
            >
              Summary
            </button>
            <button
              className={panel === "correlation" ? styles.modeActive : ""}
              type="button"
              disabled={numericColumns.length < 2}
              onClick={loadCorrelations}
            >
              Correlation
            </button>
            <button
              className={panel === "crosstab" ? styles.modeActive : ""}
              type="button"
              disabled={categoricalColumns.length < 2}
              onClick={loadCrosstab}
            >
              Crosstab
            </button>
            <button
              className={panel === "visualize" ? styles.modeActive : ""}
              type="button"
              onClick={() => buildVisualization()}
            >
              Visualize
            </button>
          </div>
        </header>

        {error ? <div className={styles.error}>{error}</div> : null}
        {busy ? (
          <div className={styles.progress}>
            <span />Calculating from canonical Parquet…
          </div>
        ) : null}

        {panel === "column" ? (
          <div className={styles.columnSummary}>
            <div className={styles.metricGrid}>
              <article>
                <span>Observed</span>
                <strong>{descriptives?.valid_count.toLocaleString() ?? "—"}</strong>
                <small>
                  {descriptives ? `${descriptives.missing_count.toLocaleString()} missing` : ""}
                </small>
              </article>
              <article>
                <span>Distinct</span>
                <strong>{descriptives?.distinct_count.toLocaleString() ?? "—"}</strong>
                <small>
                  {descriptives
                    ? `${(
                        (descriptives.distinct_count / Math.max(1, descriptives.valid_count)) *
                        100
                      ).toFixed(1)}% unique`
                    : ""}
                </small>
              </article>
              <article><span>Mean</span><strong>{metricValue(descriptives?.mean ?? null)}</strong><small>Numeric only</small></article>
              <article><span>Median</span><strong>{metricValue(descriptives?.median ?? null)}</strong><small>50th percentile</small></article>
              <article><span>Std. deviation</span><strong>{metricValue(descriptives?.stddev ?? null)}</strong><small>Sample SD</small></article>
              <article><span>Mode</span><strong>{descriptives ? displayValue(descriptives.mode) : "—"}</strong><small>{descriptives?.mode_count ? `${descriptives.mode_count.toLocaleString()} rows` : ""}</small></article>
            </div>

            <div className={styles.detailGrid}>
              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <div><p className="eyebrow">Descriptive statistics</p><h3>Five-number context</h3></div>
                  <span>{selectedColumn.data_type}</span>
                </div>
                <dl className={styles.statList}>
                  <div><dt>Minimum</dt><dd>{descriptives ? displayValue(descriptives.minimum) : "—"}</dd></div>
                  <div><dt>Q1</dt><dd>{metricValue(descriptives?.q1 ?? null)}</dd></div>
                  <div><dt>Median</dt><dd>{metricValue(descriptives?.median ?? null)}</dd></div>
                  <div><dt>Q3</dt><dd>{metricValue(descriptives?.q3 ?? null)}</dd></div>
                  <div><dt>Maximum</dt><dd>{descriptives ? displayValue(descriptives.maximum) : "—"}</dd></div>
                </dl>
                <div className={styles.contextActions}>
                  {NUMERIC_TYPES.has(selectedColumn.data_type) ? (
                    <>
                      <button type="button" onClick={() => buildVisualization("histogram")}>Histogram</button>
                      <button type="button" onClick={() => buildVisualization("box")}>Box plot</button>
                      <button type="button" onClick={() => buildVisualization("qq")}>Q-Q plot</button>
                    </>
                  ) : (
                    <button type="button" onClick={() => buildVisualization("bar")}>Frequency bar chart</button>
                  )}
                </div>
              </section>

              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <div><p className="eyebrow">Frequency table</p><h3>Most common values</h3></div>
                  <span>{frequencies?.truncated ? "Top 30" : "All shown"}</span>
                </div>
                <div className={styles.frequencyTable}>
                  <div className={styles.tableHead}><span>Value</span><span>Count</span><span>Share</span></div>
                  {frequencies?.items.map((item, index) => (
                    <div className={styles.tableRow} key={`${index}-${String(item.value)}`}>
                      <span title={displayValue(item.value)}>{displayValue(item.value)}</span>
                      <strong>{item.count.toLocaleString()}</strong>
                      <span>{item.percentage.toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
        ) : null}

        {panel === "correlation" ? (
          <section className={styles.card}>
            <div className={styles.cardHeader}>
              <div><p className="eyebrow">Relationship analysis</p><h3>Pearson correlation matrix</h3></div>
              <span>{correlations?.columns.length ?? numericColumns.length} numeric columns</span>
            </div>
            {correlations ? (
              <div className={styles.matrixWrap}>
                <table className={styles.matrix}>
                  <thead><tr><th />{correlations.columns.map((column) => <th key={column.column_id}>{column.name}</th>)}</tr></thead>
                  <tbody>
                    {correlations.columns.map((rowColumn, rowIndex) => (
                      <tr key={rowColumn.column_id}>
                        <th>{rowColumn.name}</th>
                        {correlations.matrix[rowIndex].map((value, columnIndex) => (
                          <td
                            key={correlations.columns[columnIndex].column_id}
                            data-strength={
                              value === null
                                ? "none"
                                : Math.abs(value) >= 0.7
                                  ? "strong"
                                  : Math.abs(value) >= 0.4
                                    ? "medium"
                                    : "weak"
                            }
                          >
                            {value === null ? "—" : value.toFixed(3)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <div className={styles.contextActions}>
              <button type="button" onClick={() => buildVisualization("heatmap")}>Open heatmap</button>
            </div>
          </section>
        ) : null}

        {panel === "crosstab" ? (
          <section className={styles.card}>
            <div className={styles.cardHeader}>
              <div><p className="eyebrow">Crosstab</p><h3>Category intersection</h3></div>
              <button type="button" onClick={loadCrosstab}>Recalculate</button>
            </div>
            <div className={styles.selectorRow}>
              <label>
                <span>Rows</span>
                <select value={crosstabRowId} onChange={(event) => { setCrosstabRowId(event.target.value); setCrosstab(null); }}>
                  {categoricalColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name}</option>)}
                </select>
              </label>
              <label>
                <span>Columns</span>
                <select value={crosstabColumnId} onChange={(event) => { setCrosstabColumnId(event.target.value); setCrosstab(null); }}>
                  {categoricalColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name}</option>)}
                </select>
              </label>
            </div>
            {crosstab ? (
              <div className={styles.matrixWrap}>
                <table className={styles.crosstab}>
                  <thead>
                    <tr><th>{crosstab.row_column.name}</th>{crosstab.column_values.map((value, index) => <th key={index}>{displayValue(value)}</th>)}<th>Total</th></tr>
                  </thead>
                  <tbody>
                    {crosstab.row_values.map((value, rowIndex) => (
                      <tr key={rowIndex}>
                        <th>{displayValue(value)}</th>
                        {crosstab.counts[rowIndex].map((count, columnIndex) => <td key={columnIndex}>{count.toLocaleString()}</td>)}
                        <td><strong>{crosstab.row_totals[rowIndex].toLocaleString()}</strong></td>
                      </tr>
                    ))}
                    <tr>
                      <th>Total</th>
                      {crosstab.column_totals.map((count, index) => <td key={index}><strong>{count.toLocaleString()}</strong></td>)}
                      <td><strong>{crosstab.total.toLocaleString()}</strong></td>
                    </tr>
                  </tbody>
                </table>
                <p className="dataset-meta">
                  {crosstab.row_truncated || crosstab.column_truncated
                    ? "Showing the most frequent categories. Totals cover only the displayed intersections and exclude missing values."
                    : "Totals exclude rows with missing values in either column."}
                </p>
              </div>
            ) : null}
          </section>
        ) : null}

        {panel === "visualize" ? (
          <section className={styles.visualizationLayout}>
            <aside className={styles.chartTools}>
              <div><p className="eyebrow">Chart builder</p><h3>Visualization</h3></div>
              <div className={styles.chartTypeGrid}>
                {CHARTS.map((chart) => (
                  <button
                    type="button"
                    disabled={!chartSupported(chart.type, selectedColumn, secondaryColumn)}
                    className={chartType === chart.type ? styles.chartTypeActive : ""}
                    key={chart.type}
                    onClick={() => buildVisualization(chart.type)}
                  >
                    <strong>{chart.label}</strong>
                    <span>{chart.description}</span>
                  </button>
                ))}
              </div>
              <label>
                <span>X / primary variable</span>
                <select
                  value={selectedColumn.column_id}
                  onChange={(event) => {
                    setSelectedColumnId(event.target.value);
                    setVisualization(null);
                  }}
                >
                  {profile.columns.map((column) => (
                    <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.data_type}</option>
                  ))}
                </select>
              </label>
              {chartType === "line" || chartType === "scatter" || chartType === "box" ? (
                <label>
                  <span>{chartType === "box" ? "Optional grouping variable" : "Y variable"}</span>
                  <select
                    value={secondaryColumn?.column_id ?? ""}
                    onChange={(event) => {
                      setSecondaryColumnId(event.target.value);
                      setVisualization(null);
                    }}
                  >
                    {profile.columns.map((column) => (
                      <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.data_type}</option>
                    ))}
                  </select>
                </label>
              ) : null}
              <button
                className={styles.runButton}
                type="button"
                disabled={busy || !chartSupported(chartType, selectedColumn, secondaryColumn)}
                onClick={() => buildVisualization()}
              >
                Run visualization
              </button>
            </aside>
            <div className={styles.chartCanvas}>
              {visualization ? (
                <ExploreChart result={visualization} />
              ) : (
                <div className={styles.chartEmpty}>
                  <strong>No visualization yet</strong>
                  <span>Choose a chart and run it against version {profile.version_number}.</span>
                </div>
              )}
            </div>
          </section>
        ) : null}
      </section>
    </section>
  );
}

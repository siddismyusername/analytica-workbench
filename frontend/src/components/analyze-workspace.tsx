"use client";

import { useMemo, useState } from "react";

import { ExploreChart } from "@/components/explore-chart";
import styles from "./analyze-workspace.module.css";
import type { DatasetColumnProfile, DatasetProfile } from "@/lib/dataset-upload";
import {
  type AnalysisAlternative,
  type AnalysisGoal,
  type AnalysisResult,
  type AnalysisTestId,
  type RecommendationResult,
  getAnalysisRecommendations,
  runAnalysis,
} from "@/lib/analyze-api";

const NUMERIC_TYPES = new Set(["integer", "float"]);
const CATEGORICAL_TYPES = new Set(["boolean", "string", "categorical"]);
const DIRECTIONAL_TESTS = new Set<AnalysisTestId>([
  "welch_t",
  "paired_t",
  "one_sample_t",
  "mann_whitney",
  "wilcoxon",
  "pearson",
  "spearman",
]);

const GOALS: Array<{ goal: AnalysisGoal; title: string; description: string }> = [
  {
    goal: "compare_groups",
    title: "Compare groups",
    description: "Is a numeric outcome different across independent groups?",
  },
  {
    goal: "compare_paired",
    title: "Compare paired values",
    description: "Did a row-aligned numeric measurement change?",
  },
  {
    goal: "numeric_relationship",
    title: "Measure a relationship",
    description: "Are two numeric variables associated?",
  },
  {
    goal: "categorical_association",
    title: "Test categorical association",
    description: "Are two categorical variables independent?",
  },
  {
    goal: "one_sample",
    title: "Compare with a reference",
    description: "Is a numeric mean different from a known value?",
  },
];

function formatNumber(value: number | null, digits = 4): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const absolute = Math.abs(value);
  if (absolute !== 0 && (absolute < 0.0001 || absolute >= 1_000_000)) {
    return value.toExponential(3);
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
}

function formatP(value: number): string {
  if (value < 0.0001) return "< 0.0001";
  return formatNumber(value, 4);
}

function firstColumn(columns: DatasetColumnProfile[]): string {
  return columns[0]?.column_id ?? "";
}

export function AnalyzeWorkspace({ profile }: { profile: DatasetProfile }) {
  const numericColumns = useMemo(
    () => profile.columns.filter((column) => NUMERIC_TYPES.has(column.data_type)),
    [profile.columns],
  );
  const categoricalColumns = useMemo(
    () => profile.columns.filter((column) => CATEGORICAL_TYPES.has(column.data_type)),
    [profile.columns],
  );

  const [goal, setGoal] = useState<AnalysisGoal>("compare_groups");
  const [outcomeColumnId, setOutcomeColumnId] = useState(firstColumn(numericColumns));
  const [secondaryColumnId, setSecondaryColumnId] = useState(
    numericColumns[1]?.column_id ?? firstColumn(numericColumns),
  );
  const [groupColumnId, setGroupColumnId] = useState(firstColumn(categoricalColumns));
  const [categorySecondId, setCategorySecondId] = useState(
    categoricalColumns[1]?.column_id ?? firstColumn(categoricalColumns),
  );
  const [referenceValue, setReferenceValue] = useState("0");
  const [confidenceLevel, setConfidenceLevel] = useState(0.95);
  const [alternative, setAlternative] = useState<AnalysisAlternative>("two-sided");
  const [recommendations, setRecommendations] = useState<RecommendationResult | null>(null);
  const [selectedTestId, setSelectedTestId] = useState<AnalysisTestId | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function resetForGoal(nextGoal: AnalysisGoal) {
    setGoal(nextGoal);
    setRecommendations(null);
    setSelectedTestId(null);
    setResult(null);
    setError(null);
    setAlternative("two-sided");
  }

  async function recommend() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        goal,
        outcomeColumnId: goal === "categorical_association" ? groupColumnId : outcomeColumnId,
        groupColumnId: goal === "compare_groups" ? groupColumnId : null,
        secondaryColumnId:
          goal === "categorical_association"
            ? categorySecondId
            : goal === "compare_paired" || goal === "numeric_relationship"
              ? secondaryColumnId
              : null,
      };
      const next = await getAnalysisRecommendations(profile.version_id, payload);
      setRecommendations(next);
      setSelectedTestId(next.recommendations.find((item) => item.preferred)?.test_id ?? next.recommendations[0]?.test_id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not recommend a test.");
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    if (!selectedTestId) return;
    const parsedReference = Number(referenceValue);
    if (goal === "one_sample" && !Number.isFinite(parsedReference)) {
      setError("Enter a valid numeric reference value.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await runAnalysis(profile.version_id, {
        testId: selectedTestId,
        xColumnId: goal === "categorical_association" ? groupColumnId : outcomeColumnId,
        yColumnId:
          goal === "categorical_association"
            ? categorySecondId
            : goal === "compare_paired" || goal === "numeric_relationship"
              ? secondaryColumnId
              : null,
        groupColumnId: goal === "compare_groups" ? groupColumnId : null,
        referenceValue: goal === "one_sample" ? parsedReference : null,
        confidenceLevel,
        alternative: DIRECTIONAL_TESTS.has(selectedTestId) ? alternative : "two-sided",
      });
      setResult(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not run this analysis.");
    } finally {
      setBusy(false);
    }
  }

  const hasNumeric = numericColumns.length > 0;
  const hasCategorical = categoricalColumns.length > 0;
  const configured =
    (goal === "compare_groups" && hasNumeric && hasCategorical) ||
    ((goal === "compare_paired" || goal === "numeric_relationship") && numericColumns.length >= 2) ||
    (goal === "categorical_association" && categoricalColumns.length >= 2) ||
    (goal === "one_sample" && hasNumeric);

  return (
    <section className={styles.layout} aria-label="Statistical analysis workspace">
      <aside className={styles.guide}>
        <div className={styles.heading}>
          <p className="eyebrow">Analyze</p>
          <h2>What are you trying to learn?</h2>
          <p>Choose the analytical question. Analytica will narrow the valid statistical tests.</p>
        </div>
        <div className={styles.goalList}>
          {GOALS.map((item) => (
            <button
              type="button"
              className={`${styles.goalButton} ${goal === item.goal ? styles.goalActive : ""}`}
              key={item.goal}
              onClick={() => resetForGoal(item.goal)}
            >
              <strong>{item.title}</strong>
              <span>{item.description}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className={styles.canvas}>
        <header className={styles.canvasHeader}>
          <div>
            <p className="eyebrow">Immutable version {profile.version_number}</p>
            <h2>Guided statistical analysis</h2>
            <p>Inference runs against the exact dataset version currently open in the workspace.</p>
          </div>
          <span className={styles.versionBadge}>{profile.row_count.toLocaleString()} rows</span>
        </header>

        {error ? <div className={styles.error}>{error}</div> : null}
        {busy ? <div className={styles.progress}><span />Calculating statistical evidence…</div> : null}

        <section className={styles.configCard}>
          <div className={styles.sectionHeading}>
            <div><p className="eyebrow">Variable roles</p><h3>Configure the question</h3></div>
            <span>Missing values are removed per test using complete observations.</span>
          </div>
          <div className={styles.fields}>
            {goal !== "categorical_association" ? (
              <label>
                <span>{goal === "one_sample" ? "Numeric variable" : "Outcome / primary variable"}</span>
                <select value={outcomeColumnId} onChange={(event) => { setOutcomeColumnId(event.target.value); setRecommendations(null); setResult(null); }}>
                  {numericColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.data_type}</option>)}
                </select>
              </label>
            ) : (
              <label>
                <span>First categorical variable</span>
                <select value={groupColumnId} onChange={(event) => { setGroupColumnId(event.target.value); setRecommendations(null); setResult(null); }}>
                  {categoricalColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name}</option>)}
                </select>
              </label>
            )}

            {goal === "compare_groups" ? (
              <label>
                <span>Independent group variable</span>
                <select value={groupColumnId} onChange={(event) => { setGroupColumnId(event.target.value); setRecommendations(null); setResult(null); }}>
                  {categoricalColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.distinct_count.toLocaleString()} levels</option>)}
                </select>
              </label>
            ) : null}

            {goal === "compare_paired" || goal === "numeric_relationship" ? (
              <label>
                <span>{goal === "compare_paired" ? "Second paired variable" : "Second numeric variable"}</span>
                <select value={secondaryColumnId} onChange={(event) => { setSecondaryColumnId(event.target.value); setRecommendations(null); setResult(null); }}>
                  {numericColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.data_type}</option>)}
                </select>
              </label>
            ) : null}

            {goal === "categorical_association" ? (
              <label>
                <span>Second categorical variable</span>
                <select value={categorySecondId} onChange={(event) => { setCategorySecondId(event.target.value); setRecommendations(null); setResult(null); }}>
                  {categoricalColumns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name}</option>)}
                </select>
              </label>
            ) : null}

            {goal === "one_sample" ? (
              <label>
                <span>Reference mean</span>
                <input value={referenceValue} inputMode="decimal" onChange={(event) => { setReferenceValue(event.target.value); setResult(null); }} />
              </label>
            ) : null}

            <label>
              <span>Confidence level</span>
              <select value={confidenceLevel} onChange={(event) => { setConfidenceLevel(Number(event.target.value)); setResult(null); }}>
                <option value={0.9}>90%</option>
                <option value={0.95}>95%</option>
                <option value={0.99}>99%</option>
              </select>
            </label>
          </div>
          {!configured ? <div className={styles.notice}>This dataset does not contain enough compatible columns for the selected question.</div> : null}
          <button className={styles.primaryButton} type="button" disabled={busy || !configured} onClick={recommend}>Recommend tests</button>
        </section>

        {recommendations ? (
          <section className={styles.recommendationCard}>
            <div className={styles.sectionHeading}>
              <div><p className="eyebrow">Test selector</p><h3>Recommended methods</h3></div>
              <span>{recommendations.recommendations.length} compatible</span>
            </div>
            <div className={styles.testGrid}>
              {recommendations.recommendations.map((item) => (
                <button
                  type="button"
                  className={`${styles.testButton} ${selectedTestId === item.test_id ? styles.testActive : ""}`}
                  key={item.test_id}
                  onClick={() => { setSelectedTestId(item.test_id); setResult(null); setAlternative("two-sided"); }}
                >
                  <div><strong>{item.name}</strong>{item.preferred ? <span>Preferred</span> : null}</div>
                  <p>{item.rationale}</p>
                  <small>{item.assumptions.join(" · ")}</small>
                </button>
              ))}
            </div>
            {selectedTestId && DIRECTIONAL_TESTS.has(selectedTestId) ? (
              <label className={styles.alternativeField}>
                <span>Alternative hypothesis</span>
                <select value={alternative} onChange={(event) => setAlternative(event.target.value as AnalysisAlternative)}>
                  <option value="two-sided">Two-sided</option>
                  <option value="less">Less than / negative association</option>
                  <option value="greater">Greater than / positive association</option>
                </select>
              </label>
            ) : null}
            <button className={styles.primaryButton} type="button" disabled={busy || !selectedTestId} onClick={execute}>Run selected test</button>
            <div className={styles.notes}>{recommendations.notes.map((note) => <p key={note}>{note}</p>)}</div>
          </section>
        ) : null}

        {result ? <AnalysisResultView profile={profile} result={result} /> : null}
      </section>
    </section>
  );
}

function AnalysisResultView({ profile, result }: { profile: DatasetProfile; result: AnalysisResult }) {
  const ci = result.confidence_interval;
  return (
    <section className={styles.resultCard} aria-label="Statistical result">
      <div className={styles.resultHeader}>
        <div>
          <p className="eyebrow">Result · version {profile.version_number}</p>
          <h2>{result.test_name}</h2>
          <p>{result.null_hypothesis}</p>
        </div>
        <span className={result.significant ? styles.evidenceBadge : styles.neutralBadge}>
          {result.significant ? `p < α (${result.alpha.toFixed(3)})` : `p ≥ α (${result.alpha.toFixed(3)})`}
        </span>
      </div>

      <div className={styles.resultMetrics}>
        <article><span>Estimate</span><strong>{result.estimate ? formatNumber(result.estimate.value) : "—"}</strong><small>{result.estimate?.name ?? "No single estimate"}</small></article>
        <article><span>Uncertainty</span><strong>{ci ? `${formatNumber(ci.low)} – ${formatNumber(ci.high)}` : "—"}</strong><small>{ci ? `${Math.round(ci.level * 100)}% CI · ${ci.label}` : "Not defined for this test"}</small></article>
        <article><span>Statistic</span><strong>{result.statistic.name} = {formatNumber(result.statistic.value)}</strong><small>{result.statistic.degrees_of_freedom === null ? `${result.sample_size.toLocaleString()} observations` : `df ${formatNumber(result.statistic.degrees_of_freedom)}`}</small></article>
        <article><span>p-value</span><strong>{formatP(result.p_value)}</strong><small>α = {result.alpha.toFixed(3)}</small></article>
        <article><span>Effect size</span><strong>{result.effect_size ? formatNumber(result.effect_size.value) : "—"}</strong><small>{result.effect_size ? `${result.effect_size.name}${result.effect_size.magnitude ? ` · ${result.effect_size.magnitude}` : ""}` : "Not reported"}</small></article>
      </div>

      <div className={styles.interpretation}>{result.interpretation}</div>

      {result.group_summaries.length ? (
        <section className={styles.detailCard}>
          <div className={styles.sectionHeading}><div><p className="eyebrow">Descriptive context</p><h3>Group summaries</h3></div></div>
          <div className={styles.tableWrap}><table><thead><tr><th>Group</th><th>n</th><th>Mean</th><th>Median</th><th>SD</th></tr></thead><tbody>{result.group_summaries.map((group) => <tr key={group.label}><th>{group.label}</th><td>{group.n.toLocaleString()}</td><td>{formatNumber(group.mean)}</td><td>{formatNumber(group.median)}</td><td>{formatNumber(group.stddev)}</td></tr>)}</tbody></table></div>
        </section>
      ) : null}

      <section className={styles.detailCard}>
        <div className={styles.sectionHeading}><div><p className="eyebrow">Assumptions & diagnostics</p><h3>Diagnostic evidence</h3></div></div>
        <div className={styles.diagnosticGrid}>{result.diagnostics.map((item) => <article className={styles.diagnostic} data-status={item.status} key={item.name}><div><strong>{item.name}</strong><span>{item.status}</span></div><p>{item.message}</p>{item.p_value !== null || item.statistic !== null ? <small>{item.statistic !== null ? `Statistic ${formatNumber(item.statistic)}` : ""}{item.p_value !== null ? ` · p ${formatP(item.p_value)}` : ""}</small> : null}</article>)}</div>
      </section>

      {result.warnings.length ? <div className={styles.warningList}>{result.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}

      {result.visualizations.length ? (
        <section className={styles.visualGrid}>
          {result.visualizations.map((visualization, index) => (
            <div className={styles.chartCard} key={`${visualization.chart_type}-${index}`}>
              <ExploreChart result={{ ...visualization, version_id: result.version_id }} />
            </div>
          ))}
        </section>
      ) : null}
    </section>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { Checkbox } from "@heroui/react";

import type { DatasetProfile } from "@/lib/dataset-upload";
import {
  getModelRuns,
  submitModelRun,
  type Algorithm,
  type ModelRun,
  type ProblemType,
} from "@/lib/model-api";

import { Button, Input, Select } from "./ui-controls";

import { DataTable } from "./data-table";

import styles from "./model-workspace.module.css";

const FEATURES = new Set(["integer", "float", "boolean", "string", "categorical"]);
const ALGORITHMS: Array<{ id: Algorithm; label: string }> = [
  { id: "linear", label: "Linear / logistic" },
  { id: "decision_tree", label: "Decision tree" },
  { id: "random_forest", label: "Random forest" },
];

function metricLabel(metric: string): string {
  return ({ rmse: "RMSE", mae: "MAE", r2: "R²", macro_f1: "Macro F1", accuracy: "Accuracy", balanced_accuracy: "Balanced accuracy", roc_auc: "ROC AUC" } as Record<string, string>)[metric] ?? metric;
}

function score(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(3);
}

export function ModelWorkspace({ profile }: { profile: DatasetProfile }) {
  const numericColumns = useMemo(() => profile.columns.filter((column) => ["integer", "float"].includes(column.data_type)), [profile.columns]);
  const classColumns = useMemo(() => profile.columns.filter((column) => ["integer", "boolean", "string", "categorical"].includes(column.data_type)), [profile.columns]);
  const availableFeatures = useMemo(() => profile.columns.filter((column) => FEATURES.has(column.data_type)), [profile.columns]);
  const [problemType, setProblemType] = useState<ProblemType>("regression");
  const [targetId, setTargetId] = useState(numericColumns[0]?.column_id ?? "");
  const [featureIds, setFeatureIds] = useState<string[]>(availableFeatures.filter((column) => column.column_id !== numericColumns[0]?.column_id).map((column) => column.column_id));
  const [algorithms, setAlgorithms] = useState<Algorithm[]>(["linear", "decision_tree", "random_forest"]);
  const [testFraction, setTestFraction] = useState(0.2);
  const [seed, setSeed] = useState(42);
  const [crossValidation, setCrossValidation] = useState(false);
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const targetOptions = problemType === "regression" ? numericColumns : classColumns;
  const selected = runs.find((run) => run.job_id === selectedJobId) ?? runs[0] ?? null;
  const result = selected?.result;
  const baselineScore = result?.candidates.find((candidate) => candidate.algorithm === "baseline")?.validation_score;
  const winnerScore = result?.candidates.find((candidate) => candidate.algorithm === result.best_algorithm)?.validation_score;
  const baselineBeatsWinner = baselineScore !== undefined && winnerScore !== undefined
    && (result?.primary_metric === "rmse" ? baselineScore <= winnerScore : baselineScore >= winnerScore);

  useEffect(() => {
    let cancelled = false;
    void getModelRuns(profile.version_id)
      .then((items) => { if (!cancelled) setRuns(items); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load model runs."); });
    return () => { cancelled = true; };
  }, [profile.version_id]);

  useEffect(() => {
    if (!runs.some((run) => run.status === "queued" || run.status === "running")) return;
    let active = true;
    const timer = window.setInterval(() => {
      void getModelRuns(profile.version_id)
        .then((items) => { if (active) setRuns(items); })
        .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Could not refresh model runs."); });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [profile.version_id, runs]);

  function changeProblemType(next: ProblemType) {
    setProblemType(next);
    const preferredCategory = classColumns.find((column) => ["boolean", "categorical"].includes(column.data_type))
      ?? classColumns.find((column) => column.data_type === "string")
      ?? classColumns[0];
    const nextTarget = next === "regression" ? numericColumns[0]?.column_id ?? "" : preferredCategory?.column_id ?? "";
    setTargetId(nextTarget);
    setFeatureIds(availableFeatures.filter((column) => column.column_id !== nextTarget).map((column) => column.column_id));
    setError(null);
  }

  function toggleFeature(columnId: string) {
    setFeatureIds((current) => current.includes(columnId) ? current.filter((id) => id !== columnId) : [...current, columnId]);
  }

  function toggleAlgorithm(algorithm: Algorithm) {
    setAlgorithms((current) => current.includes(algorithm) ? current.filter((id) => id !== algorithm) : [...current, algorithm]);
  }

  async function startRun() {
    if (!targetId || featureIds.length === 0 || algorithms.length === 0) {
      setError("Choose a target, at least one predictor, and at least one candidate model.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await submitModelRun(profile.version_id, {
        problem_type: problemType,
        target_column_id: targetId,
        feature_column_ids: featureIds,
        algorithms,
        test_fraction: testFraction,
        random_seed: seed,
        cross_validation: crossValidation,
      });
      setRuns((current) => [run, ...current.filter((item) => item.job_id !== run.job_id)]);
      setSelectedJobId(run.job_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start model training.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.layout} aria-label="Model workspace">
      <aside className={styles.config}>
        <p className="eyebrow">Model · Version {profile.version_number}</p>
        <h2>Build a predictive model</h2>
        <p className={styles.hint}>Compare candidates on one held-out test split. Preprocessing is fitted on training rows only.</p>
        <label className={styles.field}><span>Goal</span><Select aria-label="Model goal" value={problemType} onChange={(event) => changeProblemType(event.target.value as ProblemType)}><option value="regression">Predict a number</option><option value="classification">Predict a category</option></Select></label>
        <label className={styles.field}><span>Target</span><Select aria-label="Model target" value={targetId} onChange={(event) => { const next = event.target.value; setTargetId(next); setFeatureIds((current) => current.filter((id) => id !== next)); }}><option value="">Choose a target</option>{targetOptions.map((column) => <option key={column.column_id} value={column.column_id}>{column.display_name}</option>)}</Select></label>
        <fieldset className={styles.checkList}><legend>Predictors</legend>{availableFeatures.filter((column) => column.column_id !== targetId).map((column) => <Checkbox key={column.column_id} isSelected={featureIds.includes(column.column_id)} onChange={() => toggleFeature(column.column_id)}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><span>{column.display_name} <small>{column.data_type}</small></span></Checkbox.Content></Checkbox>)}</fieldset>
        <fieldset className={styles.checkList}><legend>Candidate models</legend>{ALGORITHMS.map((algorithm) => <Checkbox key={algorithm.id} isSelected={algorithms.includes(algorithm.id)} onChange={() => toggleAlgorithm(algorithm.id)}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><span>{algorithm.label}</span></Checkbox.Content></Checkbox>)}</fieldset>
        <div className={styles.twoFields}><label className={styles.field}><span>Test split</span><Select aria-label="Test split" value={testFraction} onChange={(event) => setTestFraction(Number(event.target.value))}><option value="0.2">20%</option><option value="0.3">30%</option><option value="0.4">40%</option></Select></label><label className={styles.field}><span>Random seed</span><Input type="number" min="0" max="4294967295" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label></div>
        <Checkbox className={styles.inlineCheck} isSelected={crossValidation} onChange={setCrossValidation}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>3-fold cross-validation on training rows</Checkbox.Content></Checkbox>
        <Button variant="primary" className={styles.submit} type="button" disabled={busy || !targetId || featureIds.length === 0 || algorithms.length === 0} onClick={startRun}>{busy ? "Starting…" : "Train and compare"}</Button>
        <p className={styles.hint}>A baseline is included automatically. Up to 100,000 rows, 40 predictors, and 100 categories per predictor.</p>
      </aside>
      <div className={styles.main}>
        <header className={styles.header}><div><p className="eyebrow">Evaluation</p><h2>Model runs</h2></div><span className={styles.version}>Version {profile.version_number}</span></header>
        {error ? <div className={styles.error} role="alert">{error}</div> : null}
        {runs.length > 0 ? <div className={styles.runList} aria-label="Saved model runs">{runs.map((run) => <Button className={run.job_id === selected?.job_id ? styles.runActive : styles.runButton} type="button" aria-pressed={run.job_id === selected?.job_id} key={run.job_id} onClick={() => setSelectedJobId(run.job_id)}><strong>{run.configuration.problem_type === "regression" ? "Regression" : "Classification"}</strong><span>{run.status} · {run.job_id.slice(0, 8)}</span></Button>)}</div> : <div className={styles.empty}>No model runs for this version yet. Choose a target and predictors, then train a candidate.</div>}
        {selected && !result ? <div className={styles.status} role="status">{selected.status === "failed" ? selected.error_detail?.message ?? "Training failed." : `Model run ${selected.status}. Results will appear here when training finishes.`}</div> : null}
        {result ? <>
          <div className={styles.summary}><div><span>Best candidate</span><strong>{result.best_algorithm.replaceAll("_", " ")}</strong></div><div><span>Training rows</span><strong>{result.train_rows.toLocaleString()}</strong></div><div><span>Untouched test rows</span><strong>{result.test_rows.toLocaleString()}</strong></div></div>
          {baselineBeatsWinner ? <p className={styles.notice}>No candidate outperformed the baseline on training validation. Review the predictors before relying on this model.</p> : null}
          {result.excluded_target_rows > 0 ? <p className={styles.hint}>{result.excluded_target_rows} rows without a target were excluded before splitting.</p> : null}
          <section className={styles.card}><h3>Comparison on held-out test data</h3><div className={styles.tableScroll}><DataTable aria-label="Candidate comparison"><thead><tr><th>Model</th>{(result.configuration.problem_type === "regression" ? ["mae", "rmse", "r2"] : ["accuracy", "balanced_accuracy", "macro_f1", "roc_auc"]).map((metric) => <th key={metric}>{metricLabel(metric)}</th>)}<th>Validation {metricLabel(result.primary_metric)}</th></tr></thead><tbody>{result.candidates.map((candidate) => <tr key={candidate.algorithm}><th>{candidate.algorithm.replaceAll("_", " ")}{candidate.algorithm === result.best_algorithm ? " · best" : ""}</th>{(result.configuration.problem_type === "regression" ? ["mae", "rmse", "r2"] : ["accuracy", "balanced_accuracy", "macro_f1", "roc_auc"]).map((metric) => <td key={metric}>{score(candidate.metrics[metric] as number | undefined)}</td>)}<td>{score(candidate.validation_score)}</td></tr>)}</tbody></DataTable></div><p className={styles.hint}>The best candidate is selected by {result.validation_method} on training rows. Test scores are reported separately. The baseline uses the training mean or most frequent class.</p></section>
          {result.configuration.problem_type === "classification" ? <section className={styles.card}><h3>Confusion matrix · best candidate</h3>{(() => { const metrics = result.candidates.find((item) => item.algorithm === result.best_algorithm)?.metrics; const labels = metrics?.class_labels as string[] | undefined; const matrix = metrics?.confusion_matrix as number[][] | undefined; return labels && matrix ? <div className={styles.tableScroll}><DataTable aria-label="Confusion matrix"><thead><tr><th>Actual ↓ / Predicted →</th>{labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{matrix.map((row, index) => <tr key={labels[index]}><th>{labels[index]}</th>{row.map((count, column) => <td key={labels[column]}>{count}</td>)}</tr>)}</tbody></DataTable></div> : null; })()}</section> : null}
          <section className={styles.card}><h3>What the best model used</h3>{result.explanation.length ? <ol className={styles.explanation}>{result.explanation.map((item) => <li key={item.feature}><span>{item.feature.replaceAll("numeric__", "").replaceAll("categorical__", "")}</span><strong>{score(item.value)}</strong></li>)}</ol> : <p>No coefficient or feature importance is available for this model.</p>}<p className={styles.hint}>{result.explanation_note}</p></section>
        </> : null}
      </div>
    </section>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Card } from "@heroui/react";

import { ExploreChart } from "@/components/explore-chart";
import type { DatasetProfile } from "@/lib/dataset-upload";
import type { VisualizationResult } from "@/lib/explore-api";
import {
  artifactDownloadUrl, createExport, getExports, getSavedResults,
  type ExportJob, type ExportKind, type SavedResult,
} from "@/lib/results-api";
import { Button, Input } from "./ui-controls";

import styles from "./results-workspace.module.css";

function summary(result: SavedResult): string {
  const value = result.payload;
  if (result.kind === "analysis") {
    const statistic = value.statistic as { name?: string; value?: number } | undefined;
    return `${statistic?.name ?? "Statistic"} ${statistic?.value?.toLocaleString() ?? "—"} · p ${typeof value.p_value === "number" ? value.p_value.toPrecision(3) : "—"}`;
  }
  if (result.kind === "model") {
    const candidates = (value.candidates as Array<{ algorithm: string; metrics: Record<string, number> }> | undefined) ?? [];
    const best = candidates.find((item) => item.algorithm === value.best_algorithm);
    const metric = String(value.primary_metric ?? "metric");
    return `${String(value.best_algorithm ?? "Model").replaceAll("_", " ")} · ${metric} ${best?.metrics?.[metric]?.toFixed(3) ?? "—"}`;
  }
  return `${String(value.chart_type ?? "Chart")} · ${Array.isArray(value.data) ? value.data.length : 0} plotted values`;
}

function variables(result: SavedResult, profile: DatasetProfile): string {
  const config = result.configuration;
  const name = (id: unknown) => profile.columns.find((column) => column.column_id === id)?.display_name ?? String(id);
  if (result.kind === "model") {
    const features = Array.isArray(config.feature_column_ids) ? config.feature_column_ids.map(name).join(", ") : "";
    return `Target: ${name(config.target_column_id)} · Predictors: ${features}`;
  }
  const ids = [config.x_column_id, config.y_column_id, config.group_column_id].filter(Boolean);
  return ids.length ? `Variables: ${ids.map(name).join(", ")}` : "";
}

function exportLabel(kind: ExportKind): string {
  return ({ dataset_csv: "Dataset · CSV", dataset_parquet: "Dataset · Parquet", report_html: "Report · HTML", chart_svg: "Chart · SVG" })[kind];
}

export function ResultsWorkspace({ profile }: { profile: DatasetProfile }) {
  const [results, setResults] = useState<SavedResult[]>([]);
  const [exports, setExports] = useState<ExportJob[]>([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [title, setTitle] = useState(`${profile.dataset_name} · Analytical report`);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storageKey = `analytica:report-selection:${profile.version_id}`;

  useEffect(() => {
    let cancelled = false;
    void Promise.all([getSavedResults(profile.version_id), getExports(profile.version_id)])
      .then(([saved, generated]) => {
        if (cancelled) return;
        setResults(saved);
        setExports(generated);
        try {
          const previous = JSON.parse(window.localStorage.getItem(storageKey) ?? "[]") as string[];
          setSelection(previous.filter((id) => saved.some((item) => item.id === id)));
        } catch { setSelection([]); }
      })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load results."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [profile.version_id, storageKey]);

  useEffect(() => {
    if (!exports.some((item) => item.status === "queued" || item.status === "running")) return;
    const timer = window.setInterval(() => {
      void getExports(profile.version_id).then(setExports).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [exports, profile.version_id]);

  function updateSelection(next: string[]) {
    setSelection(next);
    window.localStorage.setItem(storageKey, JSON.stringify(next));
  }

  function toggle(id: string) {
    updateSelection(selection.includes(id) ? selection.filter((value) => value !== id) : [...selection, id]);
  }

  function move(id: string, offset: number) {
    const next = [...selection];
    const index = next.indexOf(id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    updateSelection(next);
  }

  async function exportItem(kind: ExportKind, ids: string[] = []) {
    setBusy(true);
    setError(null);
    try {
      const created = await createExport(profile.version_id, kind, kind === "report_html" ? title : "", ids);
      if (created.job_id) setExports((current) => [created, ...current.filter((item) => item.job_id !== created.job_id)]);
      if (created.artifact_id) {
        window.location.assign(artifactDownloadUrl(created.artifact_id));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create export.");
    } finally { setBusy(false); }
  }

  const selected = selection.map((id) => results.find((result) => result.id === id)).filter((result): result is SavedResult => Boolean(result));
  return (
    <div className={styles.layout}>
      <section className={styles.main} aria-label="Saved results">
        <div className={styles.heading}><div><p className="eyebrow">Results workspace</p><h2>Saved outputs</h2><p>These snapshots belong to version {profile.version_number}. Opening them does not rerun analysis.</p></div><Button type="button" onClick={() => { setLoading(true); void getSavedResults(profile.version_id).then(setResults).catch((caught) => setError(String(caught))).finally(() => setLoading(false)); }}>Refresh</Button></div>
        {loading ? <p className={styles.empty}>Loading results…</p> : results.length === 0 ? <p className={styles.empty}>No results yet. Run a chart, statistical test, or model on this version to save it here.</p> : (
          <div className={styles.cards}>
            {results.map((result) => <Card className={styles.card} key={result.id}>
              <div className={styles.cardTop}><span className={styles.kind}>{result.kind}</span><time dateTime={result.created_at}>{new Date(result.created_at).toLocaleString()}</time></div>
              <h3>{result.title}</h3><p>{summary(result)}</p>
              <p className={styles.variables}>{variables(result, profile)}</p>
              <small>Saved · Version {profile.version_number} · {result.source_job_id ? `Run ${result.source_job_id.slice(0, 8)}` : `Result ${result.id.slice(0, 8)}`}</small>
              {Array.isArray(result.payload.warnings) && result.payload.warnings.length ? <span className={styles.warning}>{result.payload.warnings.length} warning{result.payload.warnings.length === 1 ? "" : "s"}</span> : null}
              <div className={styles.cardActions}>
                <Button type="button" onClick={() => toggle(result.id)}>{selection.includes(result.id) ? "Remove from report" : "Include in report"}</Button>
                <Button type="button" onClick={() => setExpanded(expanded === result.id ? null : result.id)}>{expanded === result.id ? "Hide details" : "Details"}</Button>
                {result.kind === "chart" ? <Button type="button" disabled={busy} onClick={() => void exportItem("chart_svg", [result.id])}>Export SVG</Button> : null}
              </div>
              {expanded === result.id ? <div className={styles.details}>
                <dl><dt>Exact version</dt><dd>{result.dataset_version_id}</dd><dt>Configuration</dt><dd><pre>{JSON.stringify(result.configuration, null, 2)}</pre></dd></dl>
                {result.kind === "chart" ? <ExploreChart result={result.payload as unknown as VisualizationResult} /> : <pre>{JSON.stringify(result.payload, null, 2)}</pre>}
              </div> : null}
            </Card>)}
          </div>
        )}
      </section>
      <aside className={styles.side}>
        <section className={styles.panel} aria-label="Report composer"><p className="eyebrow">Compose</p><h2>Analytical report</h2><p>Select saved results and arrange their order. The report includes methods, diagnostics, figures, and provenance.</p>
          <label className={styles.field}>Report title<Input value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} /></label>
          <ol className={styles.selected}>{selected.map((result, index) => <li key={result.id}><span>{result.title}</span><div><Button type="button" aria-label={`Move ${result.title} up`} disabled={index === 0} onClick={() => move(result.id, -1)}>↑</Button><Button type="button" aria-label={`Move ${result.title} down`} disabled={index === selected.length - 1} onClick={() => move(result.id, 1)}>↓</Button><Button type="button" aria-label={`Remove ${result.title}`} onClick={() => toggle(result.id)}>×</Button></div></li>)}</ol>
          {selected.length === 0 ? <p className={styles.hint}>Select one or more results to build a report.</p> : null}
          <Button variant="primary" className={styles.primary} type="button" disabled={busy || selected.length === 0 || !title.trim()} onClick={() => void exportItem("report_html", selection)}>Create report</Button>
        </section>
        <section className={styles.panel} aria-label="Dataset export"><p className="eyebrow">Export</p><h2>Dataset version</h2><p>Download the exact ready version shown in this workspace.</p><div className={styles.exportButtons}><Button type="button" disabled={busy} onClick={() => void exportItem("dataset_csv")}>CSV</Button><Button type="button" disabled={busy} onClick={() => void exportItem("dataset_parquet")}>Parquet</Button></div></section>
        <section className={styles.panel} aria-label="Export history"><p className="eyebrow">Artifacts</p><h2>Export history</h2>{exports.length === 0 ? <p className={styles.hint}>No exports yet.</p> : <div className={styles.history}>{exports.map((item) => <div key={item.job_id}><span>{item.title ?? exportLabel(item.kind)}<small>{exportLabel(item.kind)} · {new Date(item.created_at).toLocaleString()} · {item.status}</small></span>{item.artifact_id ? <a href={artifactDownloadUrl(item.artifact_id)}>Download</a> : null}{item.error_detail?.message ? <p role="alert">{item.error_detail.message}</p> : null}</div>)}</div>}</section>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
      </aside>
    </div>
  );
}

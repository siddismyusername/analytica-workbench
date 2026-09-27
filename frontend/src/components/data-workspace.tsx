"use client";

import { type CSSProperties, type DragEvent, useRef, useState } from "react";

import styles from "./prepare-workspace.module.css";
import {
  type DatasetColumnProfile,
  type DatasetIngestion,
  type DatasetPreview,
  type DatasetProfile,
  getDatasetPreview,
  getDatasetProfile,
  getIngestionStatus,
  uploadDataset,
} from "@/lib/dataset-upload";
import {
  type FilterOperator,
  type PrepareOperation,
  type Scalar,
  type TransformHistoryItem,
  type TransformJob,
  type TransformPreview,
  applyTransform,
  getTransformHistory,
  getTransformStatus,
  previewTransform,
} from "@/lib/prepare-api";

const WORKFLOW = ["Data", "Prepare", "Explore", "Analyze", "Model", "Results"] as const;
const ACCEPTED_EXTENSIONS = [".csv", ".parquet"];
const PREVIEW_PAGE_SIZE = 200;
const ROW_HEIGHT = 38;
const VIEWPORT_HEIGHT = 420;
const PREPARE_TOOLS = [
  ["fill_null", "Fill missing", "Replace nulls with a typed constant"],
  ["deduplicate", "Remove duplicates", "Keep one copy of each distinct row"],
  ["filter", "Filter rows", "Keep rows matching a condition"],
  ["cast_column", "Change type", "Convert a column to another type"],
  ["rename_column", "Rename column", "Change a column name safely"],
  ["drop_columns", "Drop column", "Remove a column from the next version"],
] as const;

type WorkspacePhase = "idle" | "uploading" | "processing" | "profiling" | "ready" | "error";
type ActiveView = "Data" | "Prepare";
type PrepareTool = (typeof PREPARE_TOOLS)[number][0];

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function datasetNameFromFile(file: File): string {
  return file.name.replace(/\.(csv|parquet)$/i, "") || "Untitled dataset";
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${unit}`;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function phaseLabel(phase: WorkspacePhase, status: DatasetIngestion | null): string {
  if (phase === "uploading") return "Uploading directly to private storage";
  if (phase === "processing") {
    return status?.status === "running" ? "Canonicalizing dataset" : "Waiting for ingestion worker";
  }
  if (phase === "profiling") return "Profiling data quality";
  return "Preparing workspace";
}

function coerceValue(raw: string, column: DatasetColumnProfile): Scalar {
  if (column.data_type === "integer") {
    const value = Number(raw);
    if (!Number.isInteger(value)) throw new Error("Enter a valid integer value.");
    return value;
  }
  if (column.data_type === "float") {
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error("Enter a valid numeric value.");
    return value;
  }
  if (column.data_type === "boolean") {
    const normalized = raw.trim().toLowerCase();
    if (normalized === "true") return true;
    if (normalized === "false") return false;
    throw new Error("Boolean values must be true or false.");
  }
  return raw;
}

function operationSummary(operation: PrepareOperation): string {
  switch (operation.type) {
    case "fill_null":
      return `Fill missing values in one column with ${String(operation.value)}.`;
    case "deduplicate":
      return "Remove duplicate rows.";
    case "filter":
      return `Filter rows using ${operation.operator}.`;
    case "cast_column":
      return `Convert a column to ${operation.target_type}.`;
    case "rename_column":
      return `Rename a column to “${operation.new_name}”.`;
    case "drop_columns":
      return `Drop ${operation.column_ids.length} column(s).`;
  }
}

function DataPreviewGrid({
  preview,
  rowCount,
  loading,
  onPageChange,
}: {
  preview: DatasetPreview;
  rowCount: number;
  loading: boolean;
  onPageChange: (offset: number) => void;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const overscan = 6;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - overscan);
  const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + overscan * 2;
  const endIndex = Math.min(preview.rows.length, startIndex + visibleCount);
  const visibleRows = preview.rows.slice(startIndex, endIndex);
  const minWidth = Math.max(760, 58 + preview.columns.length * 164);
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `58px repeat(${preview.columns.length}, minmax(164px, 1fr))`,
    minWidth,
  };
  const hasPrevious = preview.offset > 0;
  const hasNext = preview.offset + preview.rows.length < rowCount;
  const shownStart = rowCount === 0 ? 0 : preview.offset + 1;
  const shownEnd = Math.min(rowCount, preview.offset + preview.rows.length);

  return (
    <section className="dataset-table-card" aria-label="Dataset preview">
      <div className="panel-heading">
        <div><p className="eyebrow">Preview</p><h3>Data grid</h3></div>
        <div className="preview-pagination" aria-label="Preview pagination">
          <span>{shownStart.toLocaleString()}–{shownEnd.toLocaleString()} of {rowCount.toLocaleString()}</span>
          <button type="button" disabled={!hasPrevious || loading} onClick={() => onPageChange(Math.max(0, preview.offset - PREVIEW_PAGE_SIZE))}>Previous</button>
          <button type="button" disabled={!hasNext || loading} onClick={() => onPageChange(preview.offset + PREVIEW_PAGE_SIZE)}>Next</button>
        </div>
      </div>
      <div className="data-grid-scroll" style={{ height: VIEWPORT_HEIGHT }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
        <div className="data-grid-header" role="row" style={gridStyle}>
          <div className="grid-cell row-number-cell" role="columnheader">#</div>
          {preview.columns.map((column) => <div className="grid-cell column-header-cell" role="columnheader" key={column}>{column}</div>)}
        </div>
        <div className="virtual-grid-body" style={{ height: preview.rows.length * ROW_HEIGHT, minWidth }} role="rowgroup">
          {visibleRows.map((row, visibleIndex) => {
            const index = startIndex + visibleIndex;
            return (
              <div className="data-grid-row" role="row" key={`${preview.offset}-${index}`} style={{ ...gridStyle, height: ROW_HEIGHT, transform: `translateY(${index * ROW_HEIGHT}px)` }}>
                <div className="grid-cell row-number-cell" role="rowheader">{(preview.offset + index + 1).toLocaleString()}</div>
                {row.map((value, columnIndex) => (
                  <div className={value === null ? "grid-cell null-cell" : "grid-cell"} role="cell" title={formatCell(value)} key={`${preview.offset}-${index}-${preview.columns[columnIndex]}`}>{formatCell(value)}</div>
                ))}
              </div>
            );
          })}
        </div>
        {loading ? <div className="grid-loading">Loading rows…</div> : null}
      </div>
    </section>
  );
}

function TransformPreviewTable({ preview }: { preview: TransformPreview }) {
  return (
    <>
      <div className={styles.impact}>
        <article><span>Before</span><strong>{preview.input_row_count.toLocaleString()} rows</strong></article>
        <article><span>After</span><strong>{preview.output_row_count.toLocaleString()} rows</strong></article>
        <article><span>Change</span><strong>{(preview.output_row_count - preview.input_row_count).toLocaleString()} rows</strong></article>
      </div>
      <div className={styles.previewHeading}>
        <div><p className="eyebrow">Read-only preview</p><h3>Result sample</h3></div>
        <span>First {preview.rows.length.toLocaleString()} rows</span>
      </div>
      <div className={styles.previewScroll}>
        <table className={styles.previewTable}>
          <thead><tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {preview.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, columnIndex) => (
                  <td className={value === null ? styles.null : undefined} title={formatCell(value)} key={`${rowIndex}-${preview.columns[columnIndex]}`}>{formatCell(value)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function DataWorkspace() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [phase, setPhase] = useState<WorkspacePhase>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [ingestion, setIngestion] = useState<DatasetIngestion | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<ActiveView>("Data");
  const [tool, setTool] = useState<PrepareTool>("fill_null");
  const [selectedColumnId, setSelectedColumnId] = useState("");
  const [filterOperator, setFilterOperator] = useState<FilterOperator>("eq");
  const [rawValue, setRawValue] = useState("");
  const [newName, setNewName] = useState("");
  const [targetType, setTargetType] = useState<"boolean" | "integer" | "float" | "string" | "date" | "datetime">("string");
  const [transformPreviewState, setTransformPreviewState] = useState<TransformPreview | null>(null);
  const [previewedOperation, setPreviewedOperation] = useState<PrepareOperation | null>(null);
  const [history, setHistory] = useState<TransformHistoryItem[]>([]);
  const [prepareBusy, setPrepareBusy] = useState(false);
  const [prepareError, setPrepareError] = useState<string | null>(null);

  const isBusy = ["uploading", "processing", "profiling"].includes(phase);
  const toolbarTitle = profile?.dataset_name ?? (datasetName || "Untitled analysis");
  const selectedColumn = profile?.columns.find((column) => column.column_id === selectedColumnId) ?? profile?.columns[0] ?? null;

  function invalidateTransformPreview() {
    setTransformPreviewState(null);
    setPreviewedOperation(null);
    setPrepareError(null);
  }

  function chooseFile(candidate: File | null) {
    if (!candidate) return;
    const lowerName = candidate.name.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.some((extension) => lowerName.endsWith(extension))) {
      setError("Choose a CSV or Parquet file.");
      return;
    }
    setError(null);
    setFile(candidate);
    setDatasetName(datasetNameFromFile(candidate));
    setPhase("idle");
    setProfile(null);
    setPreview(null);
    setIngestion(null);
    setHistory([]);
    setUploadProgress(0);
    setActiveView("Data");
    invalidateTransformPreview();
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    chooseFile(event.dataTransfer.files.item(0));
  }

  async function waitForIngestion(initial: DatasetIngestion): Promise<DatasetIngestion> {
    let current = initial;
    for (let attempt = 0; attempt < 360; attempt += 1) {
      if (current.status === "succeeded") return current;
      if (current.status === "failed" || current.status === "cancelled") throw new Error(`Ingestion ${current.status}.`);
      await sleep(1000);
      current = await getIngestionStatus(current.job_id);
      setIngestion(current);
    }
    throw new Error("Ingestion did not complete within the expected processing window.");
  }

  async function waitForTransform(initial: TransformJob): Promise<TransformJob> {
    let current = initial;
    for (let attempt = 0; attempt < 360; attempt += 1) {
      if (current.status === "succeeded") return current;
      if (current.status === "failed" || current.status === "cancelled") {
        throw new Error(current.error_detail?.message ?? `Transformation ${current.status}.`);
      }
      await sleep(1000);
      current = await getTransformStatus(current.job_id);
    }
    throw new Error("Transformation did not complete within the expected processing window.");
  }

  async function refreshVersion(versionId: string) {
    const [nextProfile, nextPreview, nextHistory] = await Promise.all([
      getDatasetProfile(versionId),
      getDatasetPreview(versionId, 0, PREVIEW_PAGE_SIZE),
      getTransformHistory(versionId),
    ]);
    setProfile(nextProfile);
    setPreview(nextPreview);
    setHistory(nextHistory);
    setSelectedColumnId(nextProfile.columns[0]?.column_id ?? "");
  }

  async function startAnalysis() {
    if (!file || !datasetName.trim()) return;
    setError(null);
    setPhase("uploading");
    setUploadProgress(0);
    try {
      const submitted = await uploadDataset(file, datasetName.trim(), setUploadProgress);
      setIngestion(submitted);
      setPhase("processing");
      const completed = await waitForIngestion(submitted);
      if (!completed.version_id) throw new Error("Ingestion completed without a dataset version.");
      setPhase("profiling");
      await refreshVersion(completed.version_id);
      setPhase("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not prepare the dataset.");
      setPhase("error");
    }
  }

  async function loadPreview(offset: number) {
    if (!profile) return;
    setPreviewLoading(true);
    setError(null);
    try {
      setPreview(await getDatasetPreview(profile.version_id, offset, PREVIEW_PAGE_SIZE));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load preview rows.");
    } finally {
      setPreviewLoading(false);
    }
  }

  function buildOperation(): PrepareOperation {
    if (!profile) throw new Error("Load a dataset before preparing it.");
    const operation_id = crypto.randomUUID();
    if (tool === "deduplicate") return { operation_id, version: 1, type: "deduplicate" };
    if (!selectedColumn) throw new Error("Choose a column.");
    if (tool === "fill_null") {
      if (rawValue === "") throw new Error("Enter the replacement value.");
      return { operation_id, version: 1, type: "fill_null", column_id: selectedColumn.column_id, strategy: "constant", value: coerceValue(rawValue, selectedColumn) };
    }
    if (tool === "filter") {
      const nullOperator = filterOperator === "is_null" || filterOperator === "not_null";
      if (!nullOperator && rawValue === "") throw new Error("Enter a comparison value.");
      return { operation_id, version: 1, type: "filter", column_id: selectedColumn.column_id, operator: filterOperator, value: nullOperator ? null : coerceValue(rawValue, selectedColumn) };
    }
    if (tool === "cast_column") return { operation_id, version: 1, type: "cast_column", column_id: selectedColumn.column_id, target_type: targetType };
    if (tool === "rename_column") {
      if (!newName.trim()) throw new Error("Enter a new column name.");
      return { operation_id, version: 1, type: "rename_column", column_id: selectedColumn.column_id, new_name: newName.trim() };
    }
    return { operation_id, version: 1, type: "drop_columns", column_ids: [selectedColumn.column_id] };
  }

  async function previewOperation() {
    if (!profile) return;
    setPrepareBusy(true);
    setPrepareError(null);
    try {
      const operation = buildOperation();
      const result = await previewTransform(profile.version_id, operation, 50);
      setPreviewedOperation(operation);
      setTransformPreviewState(result);
    } catch (caught) {
      setPrepareError(caught instanceof Error ? caught.message : "Could not preview this operation.");
    } finally {
      setPrepareBusy(false);
    }
  }

  async function commitOperation() {
    if (!profile || !previewedOperation) return;
    setPrepareBusy(true);
    setPrepareError(null);
    try {
      const submitted = await applyTransform(profile.version_id, previewedOperation);
      const completed = await waitForTransform(submitted);
      if (!completed.version_id) throw new Error("Transformation completed without a dataset version.");
      await refreshVersion(completed.version_id);
      setTransformPreviewState(null);
      setPreviewedOperation(null);
      setRawValue("");
      setNewName("");
    } catch (caught) {
      setPrepareError(caught instanceof Error ? caught.message : "Could not apply this operation.");
    } finally {
      setPrepareBusy(false);
    }
  }

  async function openVersion(versionId: string) {
    setPrepareBusy(true);
    setPrepareError(null);
    try {
      await refreshVersion(versionId);
      invalidateTransformPreview();
    } catch (caught) {
      setPrepareError(caught instanceof Error ? caught.message : "Could not open that version.");
    } finally {
      setPrepareBusy(false);
    }
  }

  function resetWorkspace() {
    setFile(null);
    setDatasetName("");
    setPhase("idle");
    setUploadProgress(0);
    setIngestion(null);
    setProfile(null);
    setPreview(null);
    setHistory([]);
    setError(null);
    setActiveView("Data");
    invalidateTransformPreview();
    if (inputRef.current) inputRef.current.value = "";
  }

  function renderDataView() {
    if (!profile || !preview) return null;
    return (
      <section className="data-workspace" aria-label="Dataset workspace">
        <div className="dataset-overview-row">
          <div><p className="eyebrow">Ready to analyze</p><h2>{profile.dataset_name}</h2><p className="dataset-meta">Canonical Parquet · {formatBytes(profile.byte_size)} · Version {profile.version_number}</p></div>
          <div className="health-chip"><span className={profile.warnings.length === 0 ? "health-dot healthy" : "health-dot"} />{profile.warnings.length === 0 ? "No quality warnings" : `${profile.warnings.length} quality warning${profile.warnings.length === 1 ? "" : "s"}`}</div>
        </div>
        <div className="metric-grid" aria-label="Dataset summary">
          <article className="metric-card"><span>Rows</span><strong>{profile.row_count.toLocaleString()}</strong></article>
          <article className="metric-card"><span>Columns</span><strong>{profile.column_count.toLocaleString()}</strong></article>
          <article className="metric-card"><span>Missing cells</span><strong>{profile.missing_percentage.toFixed(2)}%</strong><small>{profile.missing_cells.toLocaleString()} cells</small></article>
          <article className="metric-card"><span>Duplicate rows</span><strong>{profile.duplicate_percentage.toFixed(2)}%</strong><small>{profile.duplicate_rows.toLocaleString()} rows</small></article>
        </div>
        <div className="workspace-grid">
          <DataPreviewGrid preview={preview} rowCount={profile.row_count} loading={previewLoading} onPageChange={loadPreview} />
          <aside className="profile-panel" aria-label="Dataset profile">
            <div className="panel-heading"><div><p className="eyebrow">Profile</p><h3>Columns</h3></div><span>{profile.column_count}</span></div>
            {profile.warnings.length > 0 ? <div className="quality-warning-list">{profile.warnings.map((warning) => <div className={`quality-warning ${warning.severity}`} key={warning.code}><span /><p>{warning.message}</p></div>)}</div> : null}
            <div className="column-profile-list">{profile.columns.map((column) => <article className="column-profile" key={column.column_id}><div className="column-profile-title"><strong>{column.display_name}</strong><span>{column.data_type}</span></div><div className="column-profile-stats"><span>Missing <strong>{column.null_percentage.toFixed(1)}%</strong></span><span>Distinct <strong>{column.distinct_count.toLocaleString()}</strong></span></div></article>)}</div>
          </aside>
        </div>
      </section>
    );
  }

  function renderPrepareView() {
    if (!profile) return null;
    const originalVersionId = history[0]?.input_version_id ?? profile.version_id;
    const nullOperator = filterOperator === "is_null" || filterOperator === "not_null";
    return (
      <section className={styles.layout} aria-label="Prepare workspace">
        <aside className={styles.panel}>
          <div className={styles.heading}><p className="eyebrow">Prepare</p><h2>Transform data</h2></div>
          <div className={styles.toolList}>{PREPARE_TOOLS.map(([type, label, description]) => <button type="button" className={`${styles.toolButton} ${tool === type ? styles.toolButtonActive : ""}`} key={type} onClick={() => { setTool(type); invalidateTransformPreview(); }}><strong>{label}</strong><span>{description}</span></button>)}</div>
          <div className={styles.config}>
            {tool !== "deduplicate" ? <label className={styles.field}><span>Column</span><select value={selectedColumn?.column_id ?? ""} onChange={(event) => { setSelectedColumnId(event.target.value); invalidateTransformPreview(); }}>{profile.columns.map((column) => <option value={column.column_id} key={column.column_id}>{column.display_name} · {column.data_type}</option>)}</select></label> : null}
            {tool === "fill_null" ? <label className={styles.field}><span>Replacement value</span><input value={rawValue} onChange={(event) => { setRawValue(event.target.value); invalidateTransformPreview(); }} placeholder={selectedColumn?.data_type === "boolean" ? "true or false" : "Value"} /></label> : null}
            {tool === "filter" ? <><label className={styles.field}><span>Condition</span><select value={filterOperator} onChange={(event) => { setFilterOperator(event.target.value as FilterOperator); invalidateTransformPreview(); }}><option value="eq">equals</option><option value="neq">does not equal</option><option value="gt">greater than</option><option value="gte">greater than or equal</option><option value="lt">less than</option><option value="lte">less than or equal</option><option value="is_null">is missing</option><option value="not_null">is not missing</option></select></label>{!nullOperator ? <label className={styles.field}><span>Value</span><input value={rawValue} onChange={(event) => { setRawValue(event.target.value); invalidateTransformPreview(); }} /></label> : null}</> : null}
            {tool === "cast_column" ? <label className={styles.field}><span>Target type</span><select value={targetType} onChange={(event) => { setTargetType(event.target.value as typeof targetType); invalidateTransformPreview(); }}><option value="string">String</option><option value="integer">Integer</option><option value="float">Float</option><option value="boolean">Boolean</option><option value="date">Date</option><option value="datetime">Datetime</option></select></label> : null}
            {tool === "rename_column" ? <label className={styles.field}><span>New name</span><input value={newName} maxLength={255} onChange={(event) => { setNewName(event.target.value); invalidateTransformPreview(); }} /></label> : null}
            {tool === "deduplicate" ? <p className="dataset-meta">All columns are considered. One copy of each identical row will remain.</p> : null}
            {tool === "drop_columns" ? <p className="dataset-meta">The column is removed only from the next version. Earlier versions remain intact.</p> : null}
            <div className={styles.actions}><button type="button" onClick={previewOperation} disabled={prepareBusy}>Preview</button><button className={styles.applyButton} type="button" onClick={commitOperation} disabled={prepareBusy || !previewedOperation}>Apply</button></div>
            {prepareBusy ? <span className={styles.busy}>Working</span> : null}
          </div>
        </aside>

        <section className={styles.canvas}>
          <div className={styles.canvasHeader}><div><p className="eyebrow">Preview before apply</p><h2>{profile.dataset_name}</h2><p>Every applied operation creates a new immutable dataset version.</p></div><span className={styles.versionBadge}>Version {profile.version_number}</span></div>
          {prepareError ? <div className={styles.error}>{prepareError}</div> : null}
          {transformPreviewState ? <TransformPreviewTable preview={transformPreviewState} /> : <div className={styles.emptyPreview}><div><strong>No pending preview</strong><span>Configure an operation and preview its result before applying it.</span></div></div>}
        </section>

        <aside className={`${styles.panel} ${styles.historyPanel}`}>
          <div className={styles.heading}><p className="eyebrow">Reproducibility</p><h3>Operation history</h3></div>
          <div className={styles.originalVersion}><span>Original imported version</span><button className={styles.versionButton} type="button" disabled={prepareBusy || originalVersionId === profile.version_id} onClick={() => openVersion(originalVersionId)}>Open</button></div>
          <div className={styles.historyList}>{history.length === 0 ? <p className="dataset-meta">No transformations applied yet.</p> : history.map((item) => <article className={styles.historyItem} key={item.job_id}><div className={styles.historyTop}><strong>Version {item.output_version_number}</strong><span>{item.operation.type.replaceAll("_", " ")}</span></div><p>{operationSummary(item.operation)}</p><button className={styles.historyButton} type="button" disabled={prepareBusy || item.output_version_id === profile.version_id} onClick={() => openVersion(item.output_version_id)}>Open version</button></article>)}</div>
        </aside>
      </section>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar glass-surface" aria-label="Primary navigation">
        <div className="brand-lockup"><div className="brand-mark">A</div><div><strong>Analytica</strong><span>Workbench</span></div></div>
        <nav>{WORKFLOW.map((item, index) => {
          const available = item === "Data" || (item === "Prepare" && profile !== null);
          const active = item === activeView;
          return <button className={active ? "nav-item active" : "nav-item"} key={item} type="button" disabled={!available} onClick={() => { if (item === "Data" || item === "Prepare") setActiveView(item); }}><span className="nav-index">0{index + 1}</span>{item}</button>;
        })}</nav>
        <div className="sidebar-status"><span className="status-dot" />Immutable workspace</div>
      </aside>

      <section className="workspace">
        <header className="toolbar glass-surface"><div className="toolbar-title"><p className="eyebrow">Analytica Workbench · {activeView}</p><h1>{toolbarTitle}</h1></div><div className="toolbar-actions">{profile ? <span className="version-badge">Version {profile.version_number}</span> : null}<button type="button" onClick={() => inputRef.current?.click()} disabled={isBusy || prepareBusy}>Import data</button>{profile ? <button className="primary-action" type="button" onClick={resetWorkspace}>New analysis</button> : null}</div></header>
        <input className="visually-hidden" ref={inputRef} type="file" accept=".csv,.parquet,text/csv,application/vnd.apache.parquet" onChange={(event) => chooseFile(event.target.files?.item(0) ?? null)} />

        {profile && preview ? (activeView === "Prepare" ? renderPrepareView() : renderDataView()) : (
          <section className="import-surface" aria-labelledby="import-title">
            <div className="import-copy"><p className="eyebrow">Data workspace</p><h2 id="import-title">Start with the data, not the tooling.</h2><p>Upload CSV or Parquet. Analytica creates an immutable canonical dataset, profiles its quality, and opens a bounded analytical preview.</p></div>
            <div className={file ? "drop-zone has-file" : "drop-zone"} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
              <div className="drop-zone-icon" aria-hidden="true">↑</div>
              {file ? <><div className="selected-file-row"><div><strong>{file.name}</strong><span>{formatBytes(file.size)}</span></div><button type="button" onClick={() => inputRef.current?.click()} disabled={isBusy}>Replace</button></div><label className="dataset-name-field"><span>Dataset name</span><input value={datasetName} maxLength={255} onChange={(event) => setDatasetName(event.target.value)} disabled={isBusy} /></label><button className="primary-action start-analysis-button" type="button" onClick={startAnalysis} disabled={isBusy || !datasetName.trim()}>{isBusy ? "Preparing dataset…" : "Open data workspace"}</button></> : <><strong>Drop a dataset here</strong><span>CSV or Parquet</span><button className="secondary-action" type="button" onClick={() => inputRef.current?.click()}>Choose file</button></>}
            </div>
            {isBusy ? <div className="processing-card" aria-live="polite"><div className="processing-copy"><div><p className="eyebrow">In progress</p><strong>{phaseLabel(phase, ingestion)}</strong></div><span>{phase === "uploading" ? `${uploadProgress}%` : ingestion?.status ?? "working"}</span></div><div className="progress-track" aria-hidden="true"><span style={{ width: phase === "uploading" ? `${uploadProgress}%` : phase === "processing" ? "72%" : "92%" }} /></div><div className="stage-row"><span className="complete">Upload</span><span className={phase === "processing" || phase === "profiling" ? "complete" : ""}>Ingest</span><span className={phase === "profiling" ? "complete" : ""}>Profile</span></div></div> : null}
            {error ? <div className="error-banner" role="alert"><strong>Could not prepare this dataset.</strong><span>{error}</span><button type="button" onClick={() => setPhase("idle")}>Try again</button></div> : null}
            <div className="import-footnotes"><span>Direct-to-storage upload</span><span>Immutable canonical Parquet</span><span>Reproducible dataset versions</span></div>
          </section>
        )}
      </section>
    </main>
  );
}

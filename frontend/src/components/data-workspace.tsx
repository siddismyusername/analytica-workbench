"use client";

import {
  type CSSProperties,
  type DragEvent,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  type DatasetIngestion,
  type DatasetPreview,
  type DatasetProfile,
  getDatasetPreview,
  getDatasetProfile,
  getIngestionStatus,
  uploadDataset,
} from "@/lib/dataset-upload";

const WORKFLOW = ["Data", "Prepare", "Explore", "Analyze", "Model", "Results"];
const PREVIEW_PAGE_SIZE = 200;
const ROW_HEIGHT = 38;
const VIEWPORT_HEIGHT = 420;

type WorkspacePhase =
  | "idle"
  | "uploading"
  | "processing"
  | "profiling"
  | "ready"
  | "error";

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function datasetNameFromFile(file: File): string {
  return file.name.replace(/\.(csv|parquet)$/i, "") || "Untitled dataset";
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
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
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function phaseLabel(phase: WorkspacePhase, status: DatasetIngestion | null): string {
  if (phase === "uploading") {
    return "Uploading directly to private storage";
  }
  if (phase === "processing") {
    return status?.status === "running"
      ? "Canonicalizing dataset"
      : "Waiting for ingestion worker";
  }
  if (phase === "profiling") {
    return "Profiling data quality";
  }
  return "Preparing workspace";
}

function VirtualizedPreview({
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
  const viewportRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const overscan = 6;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - overscan);
  const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + overscan * 2;
  const endIndex = Math.min(preview.rows.length, startIndex + visibleCount);
  const visibleRows = preview.rows.slice(startIndex, endIndex);
  const minWidth = Math.max(760, 58 + preview.columns.length * 164);
  const template = `58px repeat(${preview.columns.length}, minmax(164px, 1fr))`;
  const gridStyle: CSSProperties = {
    gridTemplateColumns: template,
    minWidth,
  };
  const hasPrevious = preview.offset > 0;
  const hasNext = preview.offset + preview.rows.length < rowCount;
  const shownStart = rowCount === 0 ? 0 : preview.offset + 1;
  const shownEnd = Math.min(rowCount, preview.offset + preview.rows.length);

  return (
    <section className="dataset-table-card" aria-label="Dataset preview">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Preview</p>
          <h3>Data grid</h3>
        </div>
        <div className="preview-pagination" aria-label="Preview pagination">
          <span>
            {shownStart.toLocaleString()}–{shownEnd.toLocaleString()} of{" "}
            {rowCount.toLocaleString()}
          </span>
          <button
            type="button"
            disabled={!hasPrevious || loading}
            onClick={() => onPageChange(Math.max(0, preview.offset - PREVIEW_PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            type="button"
            disabled={!hasNext || loading}
            onClick={() => onPageChange(preview.offset + PREVIEW_PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </div>

      <div
        className="data-grid-scroll"
        ref={viewportRef}
        style={{ height: VIEWPORT_HEIGHT }}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      >
        <div className="data-grid-header" role="row" style={gridStyle}>
          <div className="grid-cell row-number-cell" role="columnheader">
            #
          </div>
          {preview.columns.map((column) => (
            <div className="grid-cell column-header-cell" role="columnheader" key={column}>
              {column}
            </div>
          ))}
        </div>
        <div
          className="virtual-grid-body"
          style={{ height: preview.rows.length * ROW_HEIGHT, minWidth }}
          role="rowgroup"
        >
          {visibleRows.map((row, visibleIndex) => {
            const index = startIndex + visibleIndex;
            return (
              <div
                className="data-grid-row"
                role="row"
                key={`${preview.offset}-${index}`}
                style={{
                  ...gridStyle,
                  height: ROW_HEIGHT,
                  transform: `translateY(${index * ROW_HEIGHT}px)`,
                }}
              >
                <div className="grid-cell row-number-cell" role="rowheader">
                  {(preview.offset + index + 1).toLocaleString()}
                </div>
                {row.map((value, columnIndex) => (
                  <div
                    className={value === null ? "grid-cell null-cell" : "grid-cell"}
                    role="cell"
                    title={formatCell(value)}
                    key={`${preview.offset}-${index}-${preview.columns[columnIndex]}`}
                  >
                    {formatCell(value)}
                  </div>
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

  const isBusy = ["uploading", "processing", "profiling"].includes(phase);
  const acceptedTypes = useMemo(() => [".csv", ".parquet"], []);

  function chooseFile(candidate: File | null) {
    if (!candidate) {
      return;
    }
    const lowerName = candidate.name.toLowerCase();
    if (!acceptedTypes.some((extension) => lowerName.endsWith(extension))) {
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
    setUploadProgress(0);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    chooseFile(event.dataTransfer.files.item(0));
  }

  async function waitForCompletion(initial: DatasetIngestion): Promise<DatasetIngestion> {
    let current = initial;
    for (let attempt = 0; attempt < 360; attempt += 1) {
      if (current.status === "succeeded") {
        return current;
      }
      if (current.status === "failed" || current.status === "cancelled") {
        throw new Error(`Ingestion ${current.status}.`);
      }
      await sleep(1000);
      current = await getIngestionStatus(current.job_id);
      setIngestion(current);
    }
    throw new Error("Ingestion did not complete within the expected processing window.");
  }

  async function startAnalysis() {
    if (!file || !datasetName.trim()) {
      return;
    }
    setError(null);
    setPhase("uploading");
    setUploadProgress(0);
    try {
      const submitted = await uploadDataset(file, datasetName.trim(), setUploadProgress);
      setIngestion(submitted);
      setPhase("processing");
      const completed = await waitForCompletion(submitted);
      if (!completed.version_id) {
        throw new Error("Ingestion completed without a dataset version.");
      }
      setIngestion(completed);
      setPhase("profiling");
      const [nextProfile, nextPreview] = await Promise.all([
        getDatasetProfile(completed.version_id),
        getDatasetPreview(completed.version_id, 0, PREVIEW_PAGE_SIZE),
      ]);
      setProfile(nextProfile);
      setPreview(nextPreview);
      setPhase("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not prepare the dataset.");
      setPhase("error");
    }
  }

  async function loadPreview(offset: number) {
    if (!profile) {
      return;
    }
    setPreviewLoading(true);
    setError(null);
    try {
      const nextPreview = await getDatasetPreview(
        profile.version_id,
        offset,
        PREVIEW_PAGE_SIZE,
      );
      setPreview(nextPreview);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load preview rows.");
    } finally {
      setPreviewLoading(false);
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
    setError(null);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar glass-surface" aria-label="Primary navigation">
        <div className="brand-lockup">
          <div className="brand-mark">A</div>
          <div>
            <strong>Analytica</strong>
            <span>Workbench</span>
          </div>
        </div>
        <nav>
          {WORKFLOW.map((item, index) => (
            <button className={index === 0 ? "nav-item active" : "nav-item"} key={item} type="button">
              <span className="nav-index">0{index + 1}</span>
              {item}
            </button>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className="status-dot" />
          Local workspace
        </div>
      </aside>

      <section className="workspace">
        <header className="toolbar glass-surface">
          <div className="toolbar-title">
            <p className="eyebrow">Analytica Workbench</p>
            <h1>{profile?.dataset_name ?? datasetName || "Untitled analysis"}</h1>
          </div>
          <div className="toolbar-actions">
            {profile ? (
              <span className="version-badge">Version {profile.version_number}</span>
            ) : null}
            <button type="button" onClick={() => inputRef.current?.click()} disabled={isBusy}>
              Import data
            </button>
            {profile ? (
              <button className="primary-action" type="button" onClick={resetWorkspace}>
                New analysis
              </button>
            ) : null}
          </div>
        </header>

        <input
          className="visually-hidden"
          ref={inputRef}
          type="file"
          accept=".csv,.parquet,text/csv,application/vnd.apache.parquet"
          onChange={(event) => chooseFile(event.target.files?.item(0) ?? null)}
        />

        {profile && preview ? (
          <section className="data-workspace" aria-label="Dataset workspace">
            <div className="dataset-overview-row">
              <div>
                <p className="eyebrow">Ready to analyze</p>
                <h2>{profile.dataset_name}</h2>
                <p className="dataset-meta">
                  Canonical Parquet · {formatBytes(profile.byte_size)} · Version{" "}
                  {profile.version_number}
                </p>
              </div>
              <div className="health-chip">
                <span className={profile.warnings.length === 0 ? "health-dot healthy" : "health-dot"} />
                {profile.warnings.length === 0
                  ? "No quality warnings"
                  : `${profile.warnings.length} quality warning${profile.warnings.length === 1 ? "" : "s"}`}
              </div>
            </div>

            <div className="metric-grid" aria-label="Dataset summary">
              <article className="metric-card">
                <span>Rows</span>
                <strong>{profile.row_count.toLocaleString()}</strong>
              </article>
              <article className="metric-card">
                <span>Columns</span>
                <strong>{profile.column_count.toLocaleString()}</strong>
              </article>
              <article className="metric-card">
                <span>Missing cells</span>
                <strong>{profile.missing_percentage.toFixed(2)}%</strong>
                <small>{profile.missing_cells.toLocaleString()} cells</small>
              </article>
              <article className="metric-card">
                <span>Duplicate rows</span>
                <strong>{profile.duplicate_percentage.toFixed(2)}%</strong>
                <small>{profile.duplicate_rows.toLocaleString()} rows</small>
              </article>
            </div>

            <div className="workspace-grid">
              <VirtualizedPreview
                preview={preview}
                rowCount={profile.row_count}
                loading={previewLoading}
                onPageChange={loadPreview}
              />

              <aside className="profile-panel" aria-label="Dataset profile">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Profile</p>
                    <h3>Columns</h3>
                  </div>
                  <span>{profile.column_count}</span>
                </div>

                {profile.warnings.length > 0 ? (
                  <div className="quality-warning-list">
                    {profile.warnings.map((warning) => (
                      <div className={`quality-warning ${warning.severity}`} key={warning.code}>
                        <span />
                        <p>{warning.message}</p>
                      </div>
                    ))}
                  </div>
                ) : null}

                <div className="column-profile-list">
                  {profile.columns.map((column) => (
                    <article className="column-profile" key={column.name}>
                      <div className="column-profile-title">
                        <strong>{column.display_name}</strong>
                        <span>{column.data_type}</span>
                      </div>
                      <div className="column-profile-stats">
                        <span>
                          Missing <strong>{column.null_percentage.toFixed(1)}%</strong>
                        </span>
                        <span>
                          Distinct <strong>{column.distinct_count.toLocaleString()}</strong>
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              </aside>
            </div>
          </section>
        ) : (
          <section className="import-surface" aria-labelledby="import-title">
            <div className="import-copy">
              <p className="eyebrow">Data workspace</p>
              <h2 id="import-title">Start with the data, not the tooling.</h2>
              <p>
                Upload CSV or Parquet. Analytica creates an immutable canonical dataset,
                profiles its quality, and opens a bounded analytical preview.
              </p>
            </div>

            <div
              className={file ? "drop-zone has-file" : "drop-zone"}
              onDragOver={(event) => event.preventDefault()}
              onDrop={onDrop}
            >
              <div className="drop-zone-icon" aria-hidden="true">↑</div>
              {file ? (
                <>
                  <div className="selected-file-row">
                    <div>
                      <strong>{file.name}</strong>
                      <span>{formatBytes(file.size)}</span>
                    </div>
                    <button type="button" onClick={() => inputRef.current?.click()} disabled={isBusy}>
                      Replace
                    </button>
                  </div>
                  <label className="dataset-name-field">
                    <span>Dataset name</span>
                    <input
                      value={datasetName}
                      maxLength={255}
                      onChange={(event) => setDatasetName(event.target.value)}
                      disabled={isBusy}
                    />
                  </label>
                  <button
                    className="primary-action start-analysis-button"
                    type="button"
                    onClick={startAnalysis}
                    disabled={isBusy || !datasetName.trim()}
                  >
                    {isBusy ? "Preparing dataset…" : "Open data workspace"}
                  </button>
                </>
              ) : (
                <>
                  <strong>Drop a dataset here</strong>
                  <span>CSV or Parquet</span>
                  <button className="secondary-action" type="button" onClick={() => inputRef.current?.click()}>
                    Choose file
                  </button>
                </>
              )}
            </div>

            {isBusy ? (
              <div className="processing-card" aria-live="polite">
                <div className="processing-copy">
                  <div>
                    <p className="eyebrow">In progress</p>
                    <strong>{phaseLabel(phase, ingestion)}</strong>
                  </div>
                  <span>{phase === "uploading" ? `${uploadProgress}%` : ingestion?.status ?? "working"}</span>
                </div>
                <div className="progress-track" aria-hidden="true">
                  <span
                    style={{
                      width:
                        phase === "uploading"
                          ? `${uploadProgress}%`
                          : phase === "processing"
                            ? "72%"
                            : "92%",
                    }}
                  />
                </div>
                <div className="stage-row">
                  <span className="complete">Upload</span>
                  <span className={phase === "processing" || phase === "profiling" ? "complete" : ""}>
                    Ingest
                  </span>
                  <span className={phase === "profiling" ? "complete" : ""}>Profile</span>
                </div>
              </div>
            ) : null}

            {error ? (
              <div className="error-banner" role="alert">
                <strong>Could not prepare this dataset.</strong>
                <span>{error}</span>
                <button type="button" onClick={() => setPhase("idle")}>Try again</button>
              </div>
            ) : null}

            <div className="import-footnotes">
              <span>Direct-to-storage upload</span>
              <span>Immutable canonical Parquet</span>
              <span>Reproducible dataset version</span>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}

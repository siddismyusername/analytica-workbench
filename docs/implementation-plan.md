# Analytica Workbench implementation plan

This plan tracks work remaining after the Data, Prepare, Explore, and Analyze milestones. Each phase has a user-visible completion check. The SRS remains the source of truth for product behavior.

## Phase 1 — Complete the existing workflow locally (in progress)

- [x] Document database migrations in the local setup.
- [x] Allow development-only uploads into the backend's local artifact store, while retaining direct private Blob upload in production.
- [x] Reopen the last selected dataset version after a page reload.
- [x] Correct stale Analyze and crosstab results when their inputs change.
- [x] Exercise upload → ingestion → profile → preview through HTTP in an integration test.
- [ ] Manually verify import → prepare → reload in the browser, including error recovery.

**Done when:** a fresh checkout with local configuration can import a small CSV, prepare it, reload the page, and continue from the selected version without Blob credentials.

## Phase 2 — Supervised modeling MVP (complete locally)

- [x] Add a version-bound model run contract, durable training job, and artifacts.
- [x] Build train/test splitting before fitted imputation, encoding, and scaling.
- [x] Support a baseline and regression/classification candidates with deterministic settings and optional training-only cross-validation.
- [x] Return evaluation, comparison, and appropriate explanation data through an API and workspace.
- [x] Verify regression and classification configuration, training, comparison, and reopening after reload in the local browser.

Unsupervised modeling remains planned outside this supervised MVP.

**Done when:** one regression and one classification workflow can be configured, trained, compared, and reopened from durable results.

## Phase 3 — Results and export MVP (complete locally)

- [x] Persist analysis, chart, and model snapshots against exact dataset versions and configurations; recover earlier completed model evaluations from their saved artifacts.
- [x] Build a Results workspace for reviewing outputs, selecting report sections, and arranging their order.
- [x] Export a selected dataset version as CSV or Parquet, charts as SVG, and a structured HTML report through durable artifact references.
- [x] Verify reload, report generation without rerun, version isolation, export downloads, and migration in local tests.

The HTML report is printable to PDF from the browser. Direct PDF generation is not part of this MVP.

**Done when:** saved results survive reload, can be selected for a report, and can be exported without rerunning analyses.

## Phase 4 — Production boundary and release verification

- Add authentication and enforce ownership for datasets, versions, jobs, artifacts, uploads, and results.
- Define upload limits, retention/deletion, migrations, structured telemetry, and alerting.
- Verify accessibility, deployment bundle/runtime behavior, and the browser-to-storage-to-worker flow in the deployed environment.

**Done when:** the SRS V1 acceptance criteria pass in CI and the deployed environment, including authorization checks and operational monitoring.

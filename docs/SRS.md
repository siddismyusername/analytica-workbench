# Analytica Workbench — Software Requirements Specification

**Document type:** System / Software Requirements Specification  
**Product:** Analytica Workbench  
**Repository:** `siddismyusername/analytica-workbench`  
**Status:** Living source-of-truth  
**Baseline:** `main` after the Analyze milestone (`c283ae569aa298e87f86f2b436dc1f786ab21365`)  
**Last reviewed:** 2026-09-28

---

## 1. Purpose

This document defines the functional and non-functional requirements for Analytica Workbench, a professional no-code/low-code data-analysis application for importing tabular data, understanding data quality, preparing reproducible dataset versions, exploring distributions and relationships, running guided statistical inference, building predictive models, evaluating results, and exporting reproducible analytical outputs.

This SRS is normative for product behavior. It distinguishes between:

- **Implemented** — behavior present in the current repository and covered by the current application architecture.
- **Planned** — required product behavior that is not yet implemented.
- **Deferred** — intentionally excluded from the immediate V1 path but architecturally anticipated.

If this document conflicts with executable code for an already implemented feature, the code is the immediate operational truth and this document must be corrected. If this document defines a planned requirement, implementation should conform to this document unless the requirement is explicitly revised.

---

## 2. Product scope

Analytica Workbench shall provide a single analytical workflow:

`Data → Prepare → Explore → Analyze → Model → Results`

The product shall minimize exposed complexity without reducing analytical rigor. Advanced options should appear contextually when relevant rather than as a permanently visible wall of controls.

The application is intended for analysts, students, researchers, operators, consultants, and technically literate business users who need reliable statistical and predictive analysis without writing a full analysis program from scratch.

The product is **not** intended to replace unrestricted notebook environments, distributed data-processing systems, or dedicated high-performance compute clusters. Large or computationally expensive workloads shall be classified and routed according to the execution model described in `architecture.md`.

---

## 3. Product goals

1. Make common analytical workflows possible without code.
2. Preserve reproducibility through immutable dataset versions and explicit operation history.
3. Separate data mutation from analysis: Prepare creates new versions; Explore and Analyze are read-only.
4. Use typed, validated analytical contracts rather than arbitrary user-generated SQL or Python.
5. Surface estimates, uncertainty, effect sizes, diagnostics, and visual evidence instead of reducing statistical analysis to a p-value.
6. Keep large file transfer out of serverless API request bodies.
7. Allow interactive work to graduate to durable queued or external compute without changing the product's resource/job model.
8. Make the current dataset version visible throughout the analytical workflow.

---

## 4. Definitions

| Term | Definition |
| --- | --- |
| Dataset | Logical analytical dataset containing one or more immutable versions. |
| Dataset version | Immutable canonical snapshot of a dataset at a point in the preparation lineage. |
| Canonical dataset | Server-owned Parquet representation used for downstream analytics. |
| Artifact | Durable stored object associated with a dataset version or job. |
| Operation | Typed transformation instruction such as filtering, casting, renaming, or deduplication. |
| Pipeline | Ordered set of typed operations. |
| Job | Durable unit of deferred work with queued/running/succeeded/failed/cancelled state. |
| Stable column ID | Internal immutable identifier used to address a column independently of its display/physical name. |
| Profile | Quality and structure summary derived from a canonical dataset version. |
| Interactive execution | Bounded work executed synchronously within an API request. |
| Deferred execution | Durable work submitted as a job and processed by a queue subscriber/worker. |
| External compute | Work executed outside the Vercel Function envelope while retaining the same resource/job contracts. |

---

## 5. Users and usage model

### 5.1 Primary user

The primary user shall be able to:

1. Select or drop a CSV or Parquet file.
2. Name the analysis dataset.
3. Upload the file directly to private object storage.
4. Observe upload and ingestion progress.
5. Open the resulting immutable dataset version.
6. Inspect profile metrics, quality warnings, schema, and a bounded preview.
7. Create cleaning/transformation steps through preview-before-apply interactions.
8. Navigate prior derived versions.
9. Explore variables and relationships visually.
10. Run guided statistical analyses using valid variable roles.
11. Build and compare predictive models. **Planned.**
12. Review consolidated analytical results and export outputs. **Planned.**

### 5.2 Administrative/operational user

Operational users shall be able to deploy, monitor, migrate, and troubleshoot the service through infrastructure and application logs. A dedicated administrative UI is not currently required for V1.

---

## 6. Current implementation status

| Product area | Status | Current capability |
| --- | --- | --- |
| Repository/CI | Implemented | Polyglot monorepo, frontend/backend verification workflow. |
| Data import | Implemented | CSV/Parquet, direct private upload flow, durable ingestion. |
| Canonicalization | Implemented | Immutable canonical Parquet generation. |
| Dataset control plane | Implemented | Dataset, version, artifact, job persistence with migrations. |
| Profiling | Implemented | Rows, columns, missingness, duplicate rows, approximate cardinality, warnings. |
| Preview | Implemented | Bounded/paginated preview, frontend row virtualization. |
| Prepare | Implemented | Filter, fill-null constant, deduplicate, cast, rename, drop column, preview-before-apply, history. |
| Explore | Implemented | Descriptives, frequency, correlations, crosstabs, histogram/bar/line/scatter/box/heatmap/Q-Q. |
| Analyze | Implemented | Guided selection plus 10 inferential tests, confidence intervals where defined, effect sizes, diagnostics and linked visuals. |
| Model | Planned | Supervised/unsupervised model workflows, preprocessing, validation and comparison. |
| Results | Planned | Saved analytical result registry, report composition, exports. |
| Authentication/user isolation | Planned | No production authentication boundary exists in the current codebase. |
| Production observability | Planned | Structured telemetry, metrics, alerting and operational dashboards. |

---

# 7. Functional requirements

## 7.1 Data import and ingestion

### FR-DATA-001 — Supported input formats — Implemented
The system shall accept CSV and Parquet datasets through the primary import workflow.

### FR-DATA-002 — Direct upload — Implemented
Dataset bytes shall upload from the browser directly to object storage rather than being proxied through the FastAPI application.

### FR-DATA-003 — Server-side object verification — Implemented
The backend shall resolve and verify the uploaded storage object before creating or dispatching ingestion work. Client-reported byte size or content metadata shall not be treated as authoritative.

### FR-DATA-004 — Dataset name — Implemented
The user shall provide a dataset name between 1 and 255 characters before analysis begins.

### FR-DATA-005 — Durable ingestion — Implemented
Ingestion shall be represented as a durable job with a retrievable status.

### FR-DATA-006 — Canonicalization — Implemented
Successful ingestion shall create an immutable canonical Parquet artifact and an initial ready dataset version.

### FR-DATA-007 — Non-overwrite semantics — Implemented
Canonical dataset artifacts shall not overwrite an existing canonical artifact for another version.

### FR-DATA-008 — Stable column identity — Implemented
Every canonical schema column shall have a stable internal `column_id` independent of display or physical name.

### FR-DATA-009 — Upload size policy — Partially implemented
The backend shall support an environment-configurable maximum upload size. Production limits shall be defined by deployment/storage policy and surfaced to the user before upload when practical.

### FR-DATA-010 — Additional formats — Planned
The product may add XLSX and other tabular sources after the CSV/Parquet path is production hardened. New formats shall canonicalize into the same dataset/version model.

---

## 7.2 Profiling and data understanding

### FR-PROFILE-001 — Dataset summary — Implemented
For every ready dataset version, the system shall provide row count, column count, byte size, missing-cell count and percentage, duplicate-row count and percentage.

### FR-PROFILE-002 — Column summary — Implemented
The system shall expose each column's stable ID, display name, logical type, physical/storage type, nullability, missing count/percentage, and approximate distinct count.

### FR-PROFILE-003 — Quality warnings — Implemented
The system shall surface machine-generated quality warnings including duplicate rows, missing values, and constant-column conditions when detected.

### FR-PROFILE-004 — Bounded preview — Implemented
The system shall return preview pages with an offset of zero or greater and a limit between 1 and 200 rows.

### FR-PROFILE-005 — Preview virtualization — Implemented
The browser shall render only the currently visible subset of a preview page rather than mounting an unbounded table.

### FR-PROFILE-006 — Profile immutability — Implemented
Profiling shall not mutate the selected dataset version.

---

## 7.3 Prepare / transformation pipeline

### FR-PREP-001 — Preview before apply — Implemented
Every user-configured transformation shall be previewable without allocating a new dataset version.

### FR-PREP-002 — Immutable apply — Implemented
Applying a transformation shall create a new child dataset version and shall not modify the source version.

### FR-PREP-003 — Parent lineage — Implemented
Every derived version shall reference its parent version.

### FR-PREP-004 — Operation history — Implemented
The system shall reconstruct transformation history from persisted successful transform jobs and dataset-version lineage.

### FR-PREP-005 — Filter — Implemented
The user shall be able to filter a column with `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `is_null`, and `not_null` operators, subject to type compatibility.

### FR-PREP-006 — Fill missing constant — Implemented
The user shall be able to replace missing values in one column with a typed constant.

### FR-PREP-007 — Deduplicate — Implemented
The user shall be able to remove duplicate rows using all current columns as the duplicate key.

### FR-PREP-008 — Rename column — Implemented
The user shall be able to rename a column while retaining its stable internal column ID.

### FR-PREP-009 — Cast column — Implemented
The user shall be able to cast a column to boolean, integer, float, string, date, or datetime where conversion is valid.

### FR-PREP-010 — Drop column — Implemented
The user shall be able to drop one or more columns from a derived version without altering prior versions.

### FR-PREP-011 — Parameterized values — Implemented
User-supplied filter values shall be passed to DuckDB as query parameters rather than directly interpolated into SQL.

### FR-PREP-012 — Validated column references — Implemented
Column references shall resolve through the server-owned schema/stable-column catalog before SQL generation.

### FR-PREP-013 — Future preparation operations — Planned
The product shall eventually support additional preparation operations including richer imputation, formula columns, encoding, scaling, date extraction, split/combine, grouping, pivoting, joins, and multi-step pipeline editing.

### FR-PREP-014 — Pipeline editing — Planned
The user shall eventually be able to reorder, remove, inspect, and re-run a multi-step saved pipeline while preserving deterministic lineage.

---

## 7.4 Explore

### FR-EXP-001 — Read-only behavior — Implemented
Explore shall run against the selected immutable version and shall never allocate or mutate a dataset version.

### FR-EXP-002 — Descriptive statistics — Implemented
The system shall provide count, missing count, approximate distinct count, minimum, maximum, mode and mode count for compatible variables and mean, sample standard deviation, Q1, median and Q3 for numeric variables.

### FR-EXP-003 — Frequency table — Implemented
The system shall return bounded frequency tables with counts and percentages and shall indicate truncation when the result exceeds the requested limit.

### FR-EXP-004 — Correlation — Implemented
The system shall produce Pearson correlation matrices for compatible numeric columns.

### FR-EXP-005 — Crosstab — Implemented
The system shall produce bounded categorical crosstabs with row totals, column totals and grand total.

### FR-EXP-006 — Visualizations — Implemented
The system shall support histogram, bar, line, scatter, box, correlation heatmap and normal Q-Q visualization payloads.

### FR-EXP-007 — Bounded chart payloads — Implemented
Chart-producing analytical endpoints shall bound payload size. Scatter and Q-Q data may use bounded reservoir sampling for display because these endpoints are descriptive/visual rather than inferential.

### FR-EXP-008 — Contextual chart availability — Implemented
The frontend shall expose visualization actions based on the types and roles of selected columns.

### FR-EXP-009 — Chart renderer — Implemented
Interactive charts shall render with Apache ECharts using server-generated analytical payloads.

### FR-EXP-010 — Additional exploratory methods — Planned
Future exploration may include additional robust statistics, rank correlations, grouped descriptives, richer distribution diagnostics and configurable chart styling.

---

## 7.5 Analyze / statistical inference

### FR-AN-001 — Guided intent selection — Implemented
The Analyze workspace shall begin with an analytical question rather than an unrestricted list of tests.

Supported intents are:

- compare independent groups;
- compare paired values;
- numeric relationship;
- categorical association;
- one-sample/reference comparison.

### FR-AN-002 — Test recommendation — Implemented
The backend shall recommend compatible tests using the analytical intent, declared variable roles, column types, and observed group cardinality.

### FR-AN-003 — Supported tests — Implemented
The interactive inference engine shall support:

1. Welch independent-samples t-test;
2. paired t-test;
3. one-sample t-test;
4. Welch one-way ANOVA;
5. Mann–Whitney U;
6. Wilcoxon signed-rank;
7. Kruskal–Wallis H;
8. Pearson chi-square test of independence;
9. Pearson correlation;
10. Spearman rank correlation.

### FR-AN-004 — Missing observations — Implemented
Inferential tests shall use complete observations required for the selected test and shall communicate this behavior in the UI.

### FR-AN-005 — Alternatives — Implemented
Tests that support directional hypotheses shall support `two-sided`, `less`, and `greater` alternatives where statistically defined.

### FR-AN-006 — Confidence level — Implemented
The UI shall support at least 90%, 95%, and 99% confidence levels. The API shall accept confidence levels greater than or equal to 0.8 and less than 1.0.

### FR-AN-007 — Result order — Implemented
Statistical output shall present, where defined:

`estimate → uncertainty → statistic → p-value → effect size → diagnostics → linked visual evidence`

### FR-AN-008 — Effect sizes — Implemented
Results shall provide an applicable effect size such as Hedges' g, Cohen's d/dz, rank-biserial correlation, eta-squared, epsilon-squared, Cramér's V, Pearson r, or Spearman rho.

### FR-AN-009 — Assumption diagnostics — Implemented
The system shall provide relevant diagnostics such as Shapiro–Wilk, median-centered Levene/Brown–Forsythe behavior, expected-cell diagnostics, or design/interpretation notes.

### FR-AN-010 — Diagnostic sample bound — Implemented
Shapiro–Wilk diagnostics shall be bounded to 5,000 observations because large-sample p-value accuracy is not treated as exact by the product.

### FR-AN-011 — Interactive inference bound — Implemented
The interactive inference service shall reject inferential workloads above the configured product envelope rather than silently sampling observations. The current bound is 250,000 complete observations per interactive run.

### FR-AN-012 — Linked visuals — Implemented
Results shall include relevant diagnostic or explanatory visual payloads such as box plots, Q-Q plots, scatter plots and standardized-residual heatmaps.

### FR-AN-013 — Interpretation — Implemented
Generated interpretation shall distinguish statistical evidence from practical importance and shall not imply causal claims not supported by the design.

### FR-AN-014 — Multiple comparison/post-hoc support — Planned
ANOVA-family workflows shall eventually support appropriate post-hoc analysis and multiple-testing correction when the user requests pairwise conclusions.

### FR-AN-015 — Power analysis — Planned
The system shall eventually support prospective or retrospective power/sample-size utilities where methodologically appropriate.

---

## 7.6 Model — Planned

The following requirements define the next major product stage and are not implemented at the current baseline.

### FR-MOD-001 — Problem type selection
The user shall be able to choose or be guided into regression, binary classification, multiclass classification, or unsupervised analysis based on target/feature configuration.

### FR-MOD-002 — Feature/target roles
The user shall be able to assign target and predictor variables using stable column IDs.

### FR-MOD-003 — Leakage-safe split
Supervised workflows shall create reproducible train/test splits before fitting preprocessing parameters.

### FR-MOD-004 — Preprocessing pipeline
Imputation, encoding and scaling required for a model shall be fitted on training data and applied consistently to validation/test data.

### FR-MOD-005 — Baseline
Every supervised modeling workflow shall include an appropriate baseline model/score.

### FR-MOD-006 — Initial algorithms
Initial supported algorithms should include linear regression, logistic regression, decision trees and random forests, with the architecture allowing additional scikit-learn estimators.

### FR-MOD-007 — Cross-validation
The user shall be able to enable cross-validation with deterministic configuration where appropriate.

### FR-MOD-008 — Evaluation
Regression shall include appropriate metrics such as MAE/RMSE/R²; classification shall include confusion matrix and threshold-independent/threshold-dependent metrics appropriate to class structure.

### FR-MOD-009 — Model comparison
Comparable models trained against the same version/split configuration shall be presented in a consistent comparison view.

### FR-MOD-010 — Explainability
The product shall expose model-appropriate feature importance or coefficient information and shall distinguish model explanation from causal explanation.

### FR-MOD-011 — Durable model artifacts
Trained model artifacts and metadata shall be stored by reference, associated with a dataset version/job, and reproducibly addressable.

### FR-MOD-012 — Deferred execution
Model training that exceeds the interactive execution envelope shall run as a durable job.

---

## 7.7 Results and export — Planned

### FR-RES-001 — Result registry
Analytical and model results shall be saveable as resources tied to the exact input dataset version and configuration.

### FR-RES-002 — Results workspace
The Results stage shall consolidate saved statistical results, charts, model evaluations and provenance rather than recomputing them implicitly.

### FR-RES-003 — Export cleaned data
The user shall be able to export a selected ready dataset version in at least CSV and Parquet formats.

### FR-RES-004 — Export charts
The user shall be able to export supported charts in presentation-friendly image/vector formats when supported by the renderer.

### FR-RES-005 — Report export
The product shall support a structured analytical report containing selected results, methods, diagnostics, figures and provenance.

### FR-RES-006 — Reproducible code export
A later release should support generating equivalent Python and/or R analysis code for supported pipelines and analyses.

---

## 7.8 Authentication, authorization and tenancy — Planned for production

### FR-AUTH-001 — Authentication
Production access shall require an authenticated user or organization identity.

### FR-AUTH-002 — Resource ownership
Datasets, versions, artifacts and jobs shall belong to an authenticated ownership boundary.

### FR-AUTH-003 — Authorization
Every API operation that accesses a user resource shall verify ownership/permission before returning metadata or object references.

### FR-AUTH-004 — Private storage
Production dataset artifacts shall remain private and shall only be accessible through authorized upload/download mechanisms.

### FR-AUTH-005 — No shared-key exposure
Storage credentials, database credentials and queue credentials shall never be exposed to browser code.

**Current limitation:** the repository does not yet implement a complete production authentication/tenancy model and must not be treated as multi-tenant production secure until these requirements are implemented.

---

# 8. External interface requirements

## 8.1 Web application

The primary interface shall be a responsive browser application implemented in Next.js/React.

The current workflow shell contains six top-level stages:

1. Data
2. Prepare
3. Explore
4. Analyze
5. Model
6. Results

Unavailable stages shall be disabled rather than pretending to be functional.

## 8.2 Backend API

The backend shall expose a versioned API under `/api/v1` using JSON request/response contracts.

Current implemented route groups include:

- system health/capabilities;
- operation catalog/validation;
- dataset ingestion status;
- dataset profile and preview;
- transform preview, submission, status and history;
- Explore descriptives, frequencies, correlations, crosstabs and visualization payloads;
- Analyze recommendations and execution.

The exact OpenAPI schema generated by FastAPI is the definitive wire contract for implemented endpoints.

## 8.3 Object storage

The storage abstraction shall support:

- writing artifacts from local paths;
- materializing stored artifacts into an execution-local file when required by DuckDB/scientific libraries;
- stat/metadata lookup;
- implementation-independent object references.

Current providers are local filesystem storage for development/test and Vercel Blob for production-oriented deployment.

## 8.4 Queue

The queue abstraction shall support ingestion and transform job dispatch. Current providers are inline execution for local development/test and Vercel Queue for production-oriented deployment.

## 8.5 Database

The control plane shall use SQLAlchemy and migrations. Development/test may use SQLite; production is designed for PostgreSQL via Psycopg.

---

# 9. Data requirements

## 9.1 Dataset

A dataset shall include:

- UUID primary identity;
- human-readable name;
- next version number;
- created and updated timestamps.

## 9.2 Dataset version

A dataset version shall include:

- UUID identity;
- owning dataset ID;
- monotonically increasing version number within the dataset;
- optional parent version ID;
- state (`pending`, `ready`, `failed`);
- source format;
- row count;
- byte size;
- immutable schema snapshot;
- creation timestamp.

## 9.3 Job

A job shall include:

- UUID identity;
- kind;
- status (`queued`, `running`, `succeeded`, `failed`, `cancelled`);
- unique idempotency key;
- optional dataset/input version/output version references;
- operation payload;
- error detail;
- attempt count;
- lifecycle timestamps.

## 9.4 Artifact

An artifact shall include:

- UUID identity;
- dataset-version and/or job ownership;
- kind;
- globally unique storage key;
- content type;
- byte size;
- optional SHA-256 checksum;
- creation timestamp.

A dataset version may have no more than one artifact of a given kind. A job may have no more than one artifact of a given kind.

## 9.5 Schema

A canonical dataset schema shall contain one or more columns. Each column shall include:

- stable `column_id`;
- physical name;
- display name;
- logical type;
- optional physical/storage type;
- nullability.

Duplicate stable IDs and duplicate physical names are invalid.

---

# 10. Non-functional requirements

## 10.1 Reproducibility

### NFR-REP-001
Applied data preparation shall be represented through immutable version lineage rather than in-place mutation.

### NFR-REP-002
Analytical requests shall identify an exact dataset version.

### NFR-REP-003
Operation payloads and job metadata shall be persisted sufficiently to reconstruct transformation history.

### NFR-REP-004
Future model/results resources shall record configuration, source version, software-relevant metadata and random seeds where applicable.

---

## 10.2 Performance and bounded execution

### NFR-PERF-001
Large dataset uploads shall bypass FastAPI request bodies and go directly to object storage.

### NFR-PERF-002
Preview responses shall be bounded to at most 200 rows per request.

### NFR-PERF-003
Frequency/crosstab/chart responses shall enforce endpoint-specific bounds.

### NFR-PERF-004
Interactive inference shall never silently downsample observations for p-values or confidence intervals.

### NFR-PERF-005
Workloads that cannot reliably fit the interactive function envelope shall be represented as deferred jobs or routed to external compute.

### NFR-PERF-006
Canonical tabular storage shall use Parquet to support columnar reads and efficient DuckDB execution.

---

## 10.3 Reliability

### NFR-REL-001
Deferred job submission/execution shall be idempotent where duplicate delivery is possible.

### NFR-REL-002
Workers shall transition durable job state rather than relying on ephemeral in-memory state.

### NFR-REL-003
An ingestion or transformation failure shall not corrupt an existing ready dataset version.

### NFR-REL-004
Database schema changes shall be delivered through Alembic migrations and shall be tested for upgrade behavior.

---

## 10.4 Security

### NFR-SEC-001
User-supplied scalar filter values shall be query parameters, not SQL string interpolation.

### NFR-SEC-002
Column identifiers used in generated SQL shall be selected only from the validated server-owned schema.

### NFR-SEC-003
API request models shall reject unexpected fields where configured with `extra="forbid"`.

### NFR-SEC-004
CORS origins shall be environment configurable.

### NFR-SEC-005
Secrets shall be stored in deployment environment configuration and shall not be committed to the repository.

### NFR-SEC-006
Production multi-user deployment shall not occur before authentication, authorization, and resource ownership requirements are implemented.

---

## 10.5 Accessibility

### NFR-A11Y-001
Interactive controls shall be keyboard reachable using semantic native controls wherever possible.

### NFR-A11Y-002
The application shall expose a visible `:focus-visible` indicator.

### NFR-A11Y-003
Motion shall respect `prefers-reduced-motion`.

### NFR-A11Y-004
Color shall not be the only carrier of critical status meaning; status text or labels shall accompany color indicators.

### NFR-A11Y-005
Data tables/grids shall preserve meaningful row/column semantics where practical.

### NFR-A11Y-006 — Planned hardening
The production UI shall be audited against WCAG 2.2 AA for keyboard flow, contrast, zoom/reflow, form labeling, error messaging and chart alternatives.

---

## 10.6 Responsive behavior

### NFR-RESP-001
The application shall support desktop analytical workflows as the primary layout.

### NFR-RESP-002
At reduced widths, analytical side panels shall collapse or stack rather than force unreadable columns.

### NFR-RESP-003
At mobile widths, the persistent desktop sidebar shall become a horizontal navigation rail and nonessential toolbar metadata may be hidden.

### NFR-RESP-004
The minimum supported viewport width in the current shell is 320 px, although complex analysis is optimized for larger screens.

---

## 10.7 Maintainability

### NFR-MNT-001
Frontend and backend shall remain independently deployable applications inside the same repository.

### NFR-MNT-002
Storage, queue and persistence implementations shall remain behind explicit contracts/services.

### NFR-MNT-003
Backend domain/operation models shall use typed validation rather than unstructured dictionaries at public boundaries where practical.

### NFR-MNT-004
Feature implementation shall be gated by frontend lint/typecheck/build and backend lint/compile/test checks in CI.

---

# 11. UI state requirements

Every major workflow shall account for the following states where applicable:

- empty/not configured;
- loading/processing;
- success/ready;
- validation error;
- backend/execution failure;
- disabled/unavailable;
- partial/truncated result;
- version changed/stale result.

The UI shall not leave an old analytical result visually attached to a newly selected dataset version. Version-sensitive workspaces should reset or remount state when the selected version changes.

---

# 12. Error handling requirements

1. Invalid user input shall return actionable validation text rather than a generic failure.
2. Unknown dataset versions/jobs shall map to not-found behavior.
3. Invalid analytical configuration/type combinations shall map to validation errors rather than internal-server errors.
4. Storage/control-plane failures shall not be represented as successful jobs.
5. The frontend shall surface ingestion and transformation failures, including persisted worker error detail where available.
6. The product shall not fabricate statistical results when a test is undefined or numerically invalid.

---

# 13. Execution and deployment constraints

The current deployment baseline is Vercel with two projects from one repository:

- `frontend/` — Next.js project;
- `backend/` — FastAPI/Python project.

Large dataset transfer must follow the direct-to-object-storage design. The backend function filesystem is temporary execution storage only, never durable user storage.

Detailed researched Vercel runtime, payload, memory, duration, bundle-size, queue and Blob constraints are maintained in `serverless-architecture.md`. Those values are deployment facts and may change independently of this product SRS.

---

# 14. Technology constraints at current baseline

The current implementation uses:

**Frontend**
- Next.js 16.3.6
- React 19.x
- TypeScript 5.9.x
- Apache ECharts 6.1.0
- `@vercel/blob` 2.8.0

**Backend**
- Python 3.12
- FastAPI 0.141.1
- Pydantic 2.13.5 / pydantic-settings 2.15.0
- SQLAlchemy 2.0.54
- Alembic 1.20.0
- Psycopg 3.3.6
- DuckDB 1.5.5
- NumPy 2.5.3
- pandas 3.0.6
- SciPy 1.18.1
- scikit-learn 1.9.1
- statsmodels 0.14.6
- PyArrow 25.0.1
- Vercel Python SDK 0.11.4

Library versions are implementation details, not permanent product requirements; upgrades must preserve the behavioral requirements in this document.

---

# 15. V1 acceptance definition

V1 shall be considered functionally complete when all of the following are available through one coherent user workflow:

1. Data import and durable ingestion.
2. Dataset profile and bounded preview.
3. Reproducible preparation/version lineage.
4. Exploratory statistics and visualizations.
5. Guided core statistical inference with effect sizes and diagnostics.
6. At least one complete supervised regression workflow.
7. At least one complete supervised classification workflow.
8. Reproducible train/test evaluation and model comparison.
9. Results workspace capable of retaining selected analytical/model outputs.
10. Export of cleaned data and a structured results/report artifact.
11. Production authentication/resource ownership.
12. Production database, private object storage, queue configuration and operational monitoring.
13. Successful CI and production deployment verification.

At the current baseline, items 1–5 are substantially implemented; items 6–12 remain future work.

---

# 16. Explicit non-goals for current V1

The following are not required for the initial V1 unless separately prioritized:

- arbitrary Python/R notebook execution;
- arbitrary user SQL execution;
- distributed Spark-scale processing;
- real-time streaming analytics;
- collaborative multi-user editing of the same dataset at the same instant;
- unrestricted plugin execution inside the backend;
- GPU training as a default execution path;
- enterprise governance/catalog features beyond the resource ownership/security baseline.

These can be added later without violating the core dataset/version/job architecture.

---

# 17. Traceability by product stage

| Stage | Core requirements | Mutation behavior | Current status |
| --- | --- | --- | --- |
| Data | FR-DATA, FR-PROFILE | Creates initial canonical version | Implemented |
| Prepare | FR-PREP | Creates child versions | Implemented |
| Explore | FR-EXP | Read-only | Implemented |
| Analyze | FR-AN | Read-only | Implemented |
| Model | FR-MOD | Model resources/jobs; dataset remains immutable | Planned |
| Results | FR-RES | Saves result resources/artifacts; dataset remains immutable | Planned |

---

# 18. Related documentation

- [`architecture.md`](architecture.md) — system decomposition, data flow, persistence, execution classes and deployment architecture.
- [`UI-UX-spec.md`](UI-UX-spec.md) — visual language, interaction model, workflow behavior, responsive states and accessibility rules.
- [`serverless-architecture.md`](serverless-architecture.md) — dated Vercel deployment research and runtime constraints.
- [`../README.md`](../README.md) — repository entry point and local development commands.

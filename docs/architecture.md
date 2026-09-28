# Analytica Workbench — System Architecture

**Document type:** Technical architecture and implementation source-of-truth  
**Repository:** `siddismyusername/analytica-workbench`  
**Status:** Living document  
**Baseline:** `main` after Analyze milestone (`c283ae569aa298e87f86f2b436dc1f786ab21365`)  
**Last reviewed:** 2026-09-28

---

## 1. Architecture summary

Analytica Workbench is a polyglot monorepo containing a Next.js/React frontend and a FastAPI/Python analytical backend. The architecture is built around five durable concepts:

1. **Dataset** — logical data resource.
2. **Dataset version** — immutable canonical snapshot.
3. **Artifact** — durable object associated with a version or job.
4. **Operation** — typed transformation instruction.
5. **Job** — durable deferred execution record.

The central architectural rule is:

> Data preparation creates immutable versions; analytical reading does not mutate them.

The user workflow is:

`Data → Prepare → Explore → Analyze → Model → Results`

At the current baseline, Data, Prepare, Explore and Analyze are implemented. Model and Results are future stages that must reuse the same version/artifact/job model rather than introducing a separate data lifecycle.

---

# 2. Repository topology

```text
analytica-workbench/
├── frontend/
│   ├── src/app/
│   │   ├── api/uploads/presign/route.ts
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── src/components/
│   │   ├── data-workspace.tsx
│   │   ├── prepare-workspace.module.css
│   │   ├── explore-workspace.tsx
│   │   ├── explore-workspace.module.css
│   │   ├── explore-chart.tsx
│   │   ├── analyze-workspace.tsx
│   │   └── analyze-workspace.module.css
│   ├── src/lib/
│   │   ├── dataset-upload.ts
│   │   ├── prepare-api.ts
│   │   ├── explore-api.ts
│   │   └── analyze-api.ts
│   └── package.json
├── backend/
│   ├── app.py
│   ├── analytica_api/
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── runtime.py
│   │   ├── domain/
│   │   ├── execution/
│   │   ├── ingestion/
│   │   ├── operations/
│   │   ├── persistence/
│   │   ├── queue/
│   │   ├── routes/
│   │   ├── services/
│   │   └── storage/
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   └── vercel.json
├── docs/
│   ├── SRS.md
│   ├── UI-UX-spec.md
│   ├── architecture.md
│   └── serverless-architecture.md
└── .github/workflows/verify.yml
```

---

# 3. Deployment topology

The repository is designed for two independently deployable Vercel projects using separate Root Directories.

```text
                    ┌─────────────────────────────┐
                    │           Browser           │
                    │ Next.js UI + ECharts client │
                    └──────────────┬──────────────┘
                                   │
                 normal UI/API     │      direct private upload
                                   │
                    ┌──────────────▼──────────────┐
                    │   Frontend Vercel Project   │
                    │       root: frontend/       │
                    │                             │
                    │ Next.js app                 │
                    │ upload-presign route        │
                    └──────────────┬──────────────┘
                                   │ JSON requests
                                   │
                    ┌──────────────▼──────────────┐
                    │    Backend Vercel Project   │
                    │        root: backend/       │
                    │ FastAPI + Python analytics  │
                    └───────┬─────────┬───────────┘
                            │         │
                   metadata │         │ durable jobs
                            │         │
                    ┌───────▼───┐ ┌───▼─────────────┐
                    │ PostgreSQL│ │  Vercel Queues   │
                    │ control   │ │ ingestion /      │
                    │ plane     │ │ transforms       │
                    └───────────┘ └───┬─────────────┘
                                      │
                                      ▼
                            ingestion/transform workers
                                      │
                                      ▼
                             ┌─────────────────┐
                             │ Private Blob     │
                             │ raw + canonical  │
                             │ artifacts        │
                             └─────────────────┘
```

The current serverless constraints and source research are maintained separately in `serverless-architecture.md`. That file is dated intentionally because platform limits can change. This architecture document focuses on product boundaries that should remain stable even if a provider changes.

---

# 4. Architectural principles

## 4.1 Immutable canonical data

A ready dataset version is immutable. Any transformation produces another version instead of rewriting the source artifact.

Benefits:

- reproducibility;
- natural history/version navigation;
- safe retries;
- stable analytical references;
- straightforward provenance for future reports/models.

## 4.2 Control plane separated from data plane

The relational database stores resource metadata and execution state. Large dataset bytes live in object storage.

The database is not used as a bulk tabular dataset store.

## 4.3 Provider abstraction

Object storage and queue systems are accessed through application contracts. Local development implementations and production Vercel implementations share the same service/worker behavior.

## 4.4 Large bytes avoid API bodies

Raw datasets upload directly from the browser to private object storage. FastAPI receives a storage key/reference, not the dataset body.

The same principle should be used for future large exports and model artifacts.

## 4.5 Interactive vs deferred execution

Every workload belongs to one of three classes:

1. **Interactive** — bounded and safe inside one HTTP request.
2. **Deferred** — durable job, queue, retry and status polling.
3. **External compute** — worker outside the serverless compute envelope.

The public model uses IDs/resources rather than exposing worker placement, allowing workloads to move between classes without redesigning the frontend concept.

## 4.6 Stable identifiers over display names

Analytical and transformation APIs address columns through stable internal IDs. Rename operations may change physical/display names while preserving column identity.

## 4.7 Typed operations, not arbitrary code

The transformation API accepts a discriminated typed operation model. It does not execute arbitrary SQL/Python provided by the browser.

---

# 5. Frontend architecture

## 5.1 Framework

Current frontend stack:

- Next.js 16.3.6;
- React 19.x;
- TypeScript 5.9.x;
- Apache ECharts 6.1.0;
- `@vercel/blob` 2.8.0.

The current application is a single primary workspace rendered from `src/app/page.tsx`, with stage state coordinated by `DataWorkspace`.

## 5.2 Primary state ownership

`DataWorkspace` currently owns the cross-stage resource state needed by the implemented flow:

- selected local file;
- dataset name;
- upload/ingestion phase;
- ingestion job status;
- current dataset profile;
- current preview page;
- selected immutable version;
- transformation configuration/history;
- active workflow stage.

Explore and Analyze receive the current profile/version context. Analyze is keyed/remounted by version so result state from one version cannot accidentally persist after switching lineage.

As the product grows, this state may be extracted into a dedicated resource/session layer, but the semantic ownership rule must remain: the selected dataset version is the shared analytical source of truth.

## 5.3 API client layer

Frontend calls are grouped by domain:

- `dataset-upload.ts` — upload/ingestion/profile/preview;
- `prepare-api.ts` — transform preview/apply/status/history;
- `explore-api.ts` — descriptives/frequencies/correlations/crosstabs/visualizations;
- `analyze-api.ts` — recommendations/inference.

UI components should not duplicate backend URL or payload logic when a typed client exists.

## 5.4 Upload signing route

`frontend/src/app/api/uploads/presign/route.ts` is a Next.js server route that issues a short-lived signed private Blob upload URL.

Current behavior:

- accepts filename and exact byte size;
- accepts CSV or Parquet only;
- sanitizes filename;
- optionally enforces `MAX_UPLOAD_BYTES`;
- creates `raw/<uuid>/<filename>` namespace;
- issues a `put`-only signed token;
- limits the signed upload to the expected content type and maximum size;
- expires the token after 15 minutes;
- disables overwrite;
- uses private Blob access.

Important production security guardrail:

- in production, upload signing is disabled unless `ANALYTICA_UPLOAD_SIGNING_ENABLED=true`;
- the code explicitly describes this as a temporary guard until production authentication is configured.

Therefore a production deployment is intentionally incomplete until authenticated upload authorization/resource ownership is added.

## 5.5 Visualization boundary

The backend produces chart-ready analytical data, labels and metadata. ECharts performs client rendering.

This keeps:

- statistical/data logic in Python;
- rendering interactions in the browser;
- chart payloads inspectable/testable independently of UI layout.

---

# 6. Backend architecture

## 6.1 Framework and runtime

Current backend stack:

- Python 3.12;
- FastAPI 0.141.1;
- Pydantic 2.13.5;
- SQLAlchemy 2.0.54;
- Alembic 1.20.0;
- Psycopg 3.3.6;
- DuckDB 1.5.5;
- NumPy/SciPy/pandas/statsmodels/scikit-learn/PyArrow;
- Vercel Python SDK 0.11.4.

`backend/app.py` exports the FastAPI application used by Vercel.

## 6.2 Layers

The backend is divided into clear responsibilities.

### Routes
HTTP/Pydantic request-response contracts and HTTP error mapping.

### Services
Application use-cases and orchestration.

### Domain
Provider-independent resource records and dataset schema concepts.

### Persistence
SQLAlchemy models, repositories, database/session and unit-of-work implementation.

### Operations
Typed transformation DSL and operation registry.

### Execution
DuckDB pipeline compiler/executor.

### Ingestion
CSV/Parquet canonicalization and schema manifest generation.

### Storage
Artifact-store interface plus local and Vercel Blob implementations.

### Queue
Job-queue interface plus inline and Vercel Queue implementations/subscribers.

### Runtime
Dependency composition based on environment settings.

This separation is deliberate. Analytical services must not import Vercel-specific storage/queue implementation details directly.

---

# 7. Runtime dependency composition

`analytica_api/runtime.py` is the composition root.

It creates cached application singletons for:

- database;
- control-plane service;
- artifact store;
- ingestion worker;
- transform worker;
- job queue;
- ingestion service;
- transform service;
- preview service;
- profile service;
- Explore service;
- Analyze service.

Provider selection is environment-driven:

```text
ARTIFACT_STORE_BACKEND=local       -> LocalArtifactStore
ARTIFACT_STORE_BACKEND=vercel_blob -> VercelBlobArtifactStore

QUEUE_PROVIDER=inline              -> InlineJobQueue
QUEUE_PROVIDER=vercel              -> VercelJobQueue
```

Interactive services use the same control plane and artifact store as workers.

---

# 8. Persistent control plane

## 8.1 Database role

The relational database stores durable metadata, lineage and job state. SQLite is the development default; production is intended to use PostgreSQL.

Schema changes are managed with Alembic migrations.

## 8.2 Dataset entity

`datasets`

- `id` UUID primary key;
- `name`;
- `next_version_number`;
- created/updated timestamps.

`next_version_number` allocates monotonically increasing logical version numbers within one dataset.

## 8.3 Dataset version entity

`dataset_versions`

- `id` UUID;
- `dataset_id`;
- `version_number`;
- optional `parent_version_id`;
- state: `pending | ready | failed`;
- source format;
- row count;
- byte size;
- JSON schema snapshot;
- creation timestamp.

Constraints enforce:

- unique version number per dataset;
- positive version number;
- nonnegative row/byte counts;
- valid state.

Parent links form the immutable preparation lineage.

## 8.4 Job entity

`jobs`

- `id` UUID;
- kind;
- status: `queued | running | succeeded | failed | cancelled`;
- unique `idempotency_key`;
- optional dataset/input/output version references;
- JSON operation payload;
- JSON error detail;
- attempt count;
- created/started/completed timestamps.

The job row is authoritative for deferred execution status shown to the frontend.

## 8.5 Artifact entity

`artifacts`

- `id` UUID;
- optional dataset-version owner;
- optional job owner;
- kind;
- unique storage key;
- content type;
- byte size;
- optional SHA-256 checksum;
- creation timestamp.

Constraints require at least one owner and enforce one artifact of each kind per version/job.

---

# 9. Canonical dataset schema

The immutable schema snapshot uses `DatasetSchema` and `DatasetColumn`.

A column includes:

- stable `column_id`;
- `physical_name`;
- `display_name`;
- logical `data_type`;
- optional `storage_type`;
- `nullable`.

Current logical types:

- boolean;
- integer;
- float;
- string;
- date;
- datetime;
- categorical;
- unknown.

The schema rejects duplicate stable IDs and duplicate physical names.

### Why both physical and display name?

Rename operations need to change the name visible/used in a derived schema while analytical references remain attached to the same stable column identity.

---

# 10. Artifact storage architecture

## 10.1 Contract

`ArtifactStore` abstracts durable object operations. Services/workers work with `StorageObjectRef` rather than provider objects.

The architecture supports:

- stat/metadata lookup;
- upload from an execution-local file;
- materialization into an execution-local path.

## 10.2 Development provider

`LocalArtifactStore` stores artifacts under a configurable root (`.analytica/artifacts` by default).

It exists for local development and tests and must not be mistaken for durable serverless production storage.

## 10.3 Production provider

`VercelBlobArtifactStore` implements the same contract using Vercel Blob.

Blob access is intended to be private.

## 10.4 Storage namespaces

Current worker-generated canonical keys include patterns such as:

```text
raw/<upload-uuid>/<filename>
datasets/<dataset-id>/ingestions/<job-id>/data.parquet
datasets/<dataset-id>/transforms/<job-id>/data.parquet
```

Job IDs make output keys retry-safe and prevent unrelated operations from overwriting one another.

## 10.5 Temporary filesystem

Workers and interactive analytical services may materialize an artifact inside a temporary directory to allow DuckDB/scientific Python libraries to operate on a local file.

The temporary filesystem is execution scratch space only. No durable user state may depend on it after the request/job finishes.

---

# 11. Upload and ingestion flow

## 11.1 Browser upload sequence

```text
Browser
  │
  ├─ POST frontend /api/uploads/presign { filename, size }
  │       │
  │       └─ short-lived private Blob PUT URL
  │
  ├─ PUT dataset bytes directly to Blob
  │
  └─ POST FastAPI /api/v1/datasets/ingestions
          { name, source_key }
```

The large dataset body never traverses FastAPI.

## 11.2 Ingestion submission

`DatasetIngestionService` verifies the uploaded object through the storage provider, classifies source format, registers the durable raw-upload artifact/job, and publishes the ingestion job.

Browser-supplied size/MIME values are not the backend source of truth for the stored object.

## 11.3 Queue dispatch

Production topic:

`dataset-ingestion`

The published message contains the durable job ID. The persisted job already contains the operation/resource metadata required to execute.

## 11.4 Ingestion worker

Worker algorithm:

1. Load job from control plane.
2. Validate job kind/status/dataset relation.
3. Return existing output immediately if already succeeded.
4. Move queued/failed job into running state when appropriate.
5. Resolve `raw_upload` artifact.
6. Materialize raw object to a temporary file.
7. Canonicalize CSV/Parquet into local `data.parquet` through `IngestionEngine`.
8. Write canonical Parquet artifact to durable storage.
9. Register the ingested dataset version + canonical artifact atomically through control-plane service.
10. Recover from duplicate/retry integrity races by resolving already-created canonical artifact/version.
11. Transition job to succeeded and record output version.
12. On exception, mark a running job failed with bounded error detail and re-raise.

This is explicitly retry-aware and designed for at-least-once message delivery.

---

# 12. Prepare / transform architecture

## 12.1 Typed operation DSL

Current operation types:

```text
filter
fill_null (constant)
deduplicate
rename_column
cast_column
drop_columns
```

Every operation contains:

- unique `operation_id`;
- operation schema version (`1`);
- discriminated `type`;
- typed operation-specific fields.

Unknown fields are rejected by Pydantic models.

## 12.2 Pipeline compiler

`PipelineCompiler` receives:

- an immutable input `DatasetSchema`;
- a `PipelineSpec`;
- a canonical Parquet `DatasetSource`.

It performs two tasks:

1. evolve output schema deterministically;
2. compile operations into DuckDB SQL plus ordered parameters.

The compiler uses sequential CTEs so placeholder ordering remains stable through nested/multi-step transformations.

## 12.3 SQL safety boundary

- User scalar comparison values become DuckDB parameters.
- Column references are resolved using validated stable IDs against the server-owned schema.
- Identifier quoting is performed internally.
- The API does not accept arbitrary user SQL.

This is a core security invariant and should not be bypassed by future operation implementations.

## 12.4 Preview

Transform preview:

- runs against the selected version;
- computes transformed row count/schema/sample;
- does not write a durable output artifact;
- does not allocate a child version.

## 12.5 Apply

Transform apply:

1. persists a transform job with input version and operation payload;
2. publishes to `dataset-transform` in production;
3. worker validates persisted operation;
4. materializes input canonical artifact;
5. compiles operation to DuckDB SQL;
6. executes `COPY (...) TO output.parquet (FORMAT PARQUET, COMPRESSION ZSTD)`;
7. counts rows in output;
8. writes canonical output artifact;
9. registers a child version linked to input parent;
10. completes the job with output version ID.

Source artifacts/versions are never modified.

---

# 13. Explore execution architecture

Explore is synchronous/read-only analytical execution.

For each request:

1. resolve exact dataset version;
2. load immutable schema snapshot;
3. resolve `canonical_dataset` artifact;
4. materialize to temporary local Parquet;
5. open in-memory DuckDB connection;
6. execute bounded analytical query;
7. return structured JSON payload;
8. dispose temporary files/connection.

Current capabilities:

- per-column descriptives;
- frequency table;
- Pearson correlation matrix;
- bounded crosstab;
- histogram;
- bar;
- line;
- scatter;
- box plot;
- heatmap;
- Q-Q plot.

Payload limits exist per endpoint. Scatter/Q-Q visualization sampling is allowed because the output is for bounded visual exploration, not inferential statistics.

Explore never allocates a new dataset version.

---

# 14. Analyze execution architecture

Analyze is synchronous/read-only statistical inference over the selected immutable dataset version.

## 14.1 Recommendation service

The recommendation endpoint receives an analytical goal plus stable column role IDs.

Goals:

- `compare_groups`;
- `compare_paired`;
- `numeric_relationship`;
- `categorical_association`;
- `one_sample`.

The service validates schema/type compatibility and, where relevant, observes group cardinality before returning compatible/preferred methods.

## 14.2 Inference service

Current supported tests:

- Welch independent t;
- paired t;
- one-sample t;
- Welch one-way ANOVA;
- Mann–Whitney U;
- Wilcoxon signed-rank;
- Kruskal–Wallis H;
- Pearson chi-square independence;
- Pearson correlation;
- Spearman correlation.

## 14.3 Result contract

A result is structured into:

- version ID;
- test ID/name;
- null hypothesis;
- alternative;
- alpha;
- complete sample size;
- estimate when defined;
- confidence interval when defined;
- test statistic + degrees of freedom;
- p-value;
- threshold comparison (`significant` boolean is a convenience field, not the interpretation itself);
- effect size;
- group summaries;
- diagnostics;
- visualization payloads;
- warnings;
- neutral interpretation text.

## 14.4 Inferential integrity

Interactive inference does **not** silently sample rows to obtain p-values.

Current interactive upper envelope: 250,000 complete observations for a run.

Requests above that bound fail with an explicit analytical validation error. A future deferred/external compute implementation can lift the bound without changing the result contract.

Shapiro–Wilk normality diagnostics are capped to 5,000 observations for product correctness around p-value accuracy.

---

# 15. HTTP API architecture

The FastAPI application prefixes implemented routers with `/api/v1`.

## 15.1 Dataset endpoints

```text
POST /api/v1/datasets/ingestions
GET  /api/v1/datasets/ingestions/{job_id}
GET  /api/v1/datasets/versions/{version_id}/preview
GET  /api/v1/datasets/versions/{version_id}/profile
POST /api/v1/datasets/versions/{version_id}/transforms/preview
POST /api/v1/datasets/versions/{version_id}/transforms
GET  /api/v1/datasets/transforms/{job_id}
GET  /api/v1/datasets/versions/{version_id}/history
```

## 15.2 Explore endpoints

```text
GET  /api/v1/datasets/versions/{version_id}/explore/descriptives/{column_id}
GET  /api/v1/datasets/versions/{version_id}/explore/frequencies/{column_id}
POST /api/v1/datasets/versions/{version_id}/explore/correlations
POST /api/v1/datasets/versions/{version_id}/explore/crosstab
POST /api/v1/datasets/versions/{version_id}/explore/visualizations
```

## 15.3 Analyze endpoints

```text
POST /api/v1/datasets/versions/{version_id}/analyze/recommendations
POST /api/v1/datasets/versions/{version_id}/analyze/run
```

## 15.4 System/operation endpoints

System health/capabilities and operation catalog/validation are also mounted under `/api/v1`.

The generated FastAPI OpenAPI document is authoritative for exact implemented wire schemas.

---

# 16. Error model

Routes translate known domain/application failures into HTTP semantics.

Typical mapping:

- missing control-plane resource → `404`;
- invalid analytical/operation configuration → `422`;
- invalid upload request in frontend presign route → `400/413/415` depending cause;
- disabled production upload signing before authentication → `503`;
- unexpected exceptions → normal server error handling and logging.

Worker failures persist bounded error detail on the job so clients can observe a durable failure rather than only an ephemeral queue/function error.

---

# 17. Queue architecture and idempotency

## 17.1 Providers

`JobQueue` has two runtime implementations.

### Inline

Used in development/test. It preserves the async publisher interface but invokes the real worker handler through a background thread.

This is important: local development does not implement a fake second execution path.

### Vercel

Publishes durable messages with an idempotency key.

Current topics:

- `dataset-ingestion`;
- `dataset-transform`.

## 17.2 Retry semantics

Workers are written so a duplicate message or retry can resolve an already-succeeded output rather than create another logical version.

Patterns used:

- unique job idempotency key;
- deterministic output storage namespace using job ID;
- return existing output when job already succeeded;
- storage `put` recovery through `stat` when upload may already exist;
- database uniqueness constraints;
- ingestion integrity-race recovery by looking up canonical artifact/version;
- explicit durable state transitions.

Future model/export jobs must follow the same retry discipline.

---

# 18. Configuration

Current backend settings:

```text
ENVIRONMENT=development|test|production
CORS_ALLOWED_ORIGINS=http://localhost:3000,...
DUCKDB_THREADS=1
DATABASE_URL=sqlite+pysqlite:///./analytica.db
ARTIFACT_STORE_BACKEND=local|vercel_blob
LOCAL_ARTIFACT_ROOT=.analytica/artifacts
QUEUE_PROVIDER=inline|vercel
MAX_UPLOAD_BYTES=<optional positive integer>
```

Production Blob credentials are expected through a connected Blob store/OIDC or appropriate deployment secret configuration.

Frontend upload-signing configuration includes:

```text
MAX_UPLOAD_BYTES=<optional positive integer>
ANALYTICA_UPLOAD_SIGNING_ENABLED=true   # required in production until auth integration changes this design
```

Secrets must never be committed.

---

# 19. Local-development topology

Local default:

```text
Browser
  │
  ▼
Next.js localhost:3000
  │
  ├─ local upload signing/dev Blob behavior as configured
  │
  ▼
FastAPI local server
  │
  ├─ SQLite metadata database
  ├─ LocalArtifactStore (.analytica/artifacts)
  └─ InlineJobQueue -> real ingestion/transform workers
```

The local stack intentionally reuses production service/worker contracts so behavior differences are concentrated in provider adapters.

---

# 20. Production target topology

Production target:

```text
Frontend Vercel Project
  ├─ Next.js app
  └─ authenticated upload signing route (authentication still to be implemented)

Backend Vercel Project
  └─ FastAPI Python Functions
       ├─ PostgreSQL control plane
       ├─ Vercel Blob artifact store
       └─ Vercel Queue publisher/subscribers
```

Production prerequisites not yet complete:

- authentication;
- ownership/authorization checks;
- production database provisioning/migration process;
- telemetry/alerting;
- final upload policy/limits;
- deployment verification of the complete scientific dependency bundle;
- security and accessibility audit.

---

# 21. Security architecture

## 21.1 Implemented safeguards

- Private signed object upload design.
- Short-lived upload authorization (15 minutes in current frontend route).
- Upload content type and maximum exact size are encoded into the signed request.
- Overwrite disabled for raw upload path.
- Sanitized file name plus server-generated UUID namespace.
- Server verifies stored source object during ingestion submission.
- Pydantic typed request validation.
- Unexpected fields forbidden on many mutation/analysis payloads.
- Parameterized transformation values.
- Server-controlled column resolution/identifier quoting.
- No arbitrary SQL or Python execution endpoint.
- Configurable CORS origins.

## 21.2 Missing production boundary

The current architecture does not yet contain a complete user authentication/resource ownership layer.

This is not a small UI omission. Before a public multi-user production launch, the schema/service/API boundaries must enforce ownership of:

- datasets;
- versions;
- artifacts;
- jobs;
- saved analyses;
- models;
- exports.

The upload-signing route deliberately defaults to disabled in production until that boundary exists.

## 21.3 Future ownership design

Preferred direction:

- introduce authenticated principal/context at HTTP boundary;
- attach resource owner/workspace/org ID to root resources;
- make repository/service methods ownership-aware;
- avoid relying on unguessable UUIDs as authorization;
- authorize both metadata access and Blob URL/token issuance.

---

# 22. Performance architecture

## 22.1 Parquet + DuckDB

Canonical storage is Parquet because downstream workloads frequently need scans, projection, grouping and analytical functions. DuckDB executes directly against the canonical file once materialized.

## 22.2 Bounded responses

Current safeguards include:

- preview limit ≤ 200;
- bounded frequency results;
- crosstab category limits;
- visualization data limits;
- reservoir sampling for visual-only scatter/Q-Q payloads;
- explicit interactive inference observation ceiling.

## 22.3 Materialization trade-off

Current analytical services materialize private Blob artifacts to execution-local temporary files. This is simple and provider-independent, but means each request may download the full canonical artifact even if DuckDB reads only selected columns.

This is acceptable for the current implementation envelope but should be benchmarked. Possible future optimizations include:

- signed/private remote Parquet reads if provider/security behavior permits;
- caching/materialization reuse within durable workers;
- partitioning for very large datasets;
- moving large analysis to dedicated workers with local ephemeral disks;
- explicit dataset-size tiers and execution planning.

Do not introduce these optimizations before measurement demonstrates the need.

## 22.4 Scientific function bundle

The backend intentionally includes a large scientific Python stack. Deployment package size/cold-start/memory behavior must be measured in deployed environments. `serverless-architecture.md` records current Vercel limits researched when the backend was designed.

---

# 23. CI and quality gates

`.github/workflows/verify.yml` verifies frontend and backend independently.

Frontend gate:

- dependency install;
- ESLint;
- TypeScript `tsc --noEmit`;
- Next.js production build.

Backend gate:

- dependency install;
- Ruff;
- Python byte-compilation;
- pytest suite.

The current backend test suite covers:

- API/system behavior;
- operation compiler/execution;
- ingestion;
- control-plane persistence;
- migrations;
- storage safety;
- durable jobs/idempotency;
- profiling/preview;
- transformations/version lineage;
- Explore queries;
- Analyze statistical families.

A PR should not be merged after feature work if its applicable CI checks are failing.

---

# 24. Planned Model architecture

Model must extend the current system rather than bypass it.

Proposed resource flow:

```text
Dataset Version
   │
   ├─ Model Run configuration
   │     ├─ target column ID
   │     ├─ feature column IDs
   │     ├─ split/CV config
   │     ├─ preprocessing config
   │     ├─ estimator config
   │     └─ seed
   │
   ▼
Durable model-training Job
   │
   ▼
Worker / external compute
   │
   ├─ fitted pipeline artifact
   ├─ evaluation artifact
   ├─ predictions artifact (optional/bounded)
   └─ explainability artifact
```

Key rules:

- source dataset version remains immutable;
- train/test split occurs before fitting preprocessing;
- preprocessing and estimator belong to one fitted pipeline;
- random seeds/config are persisted;
- model artifacts are saved by reference;
- heavy runs are deferred;
- result metadata is stable if the worker later moves outside Vercel.

A future schema migration will be required for persistent model/result resources unless they are initially represented as specialized job/artifact records.

---

# 25. Planned Results architecture

Results should introduce a durable result resource tied to:

- exact dataset version;
- originating analysis/model job or request configuration;
- type;
- summary metadata;
- zero or more artifacts.

Report generation should operate on saved result IDs, not re-run analyses implicitly.

Large report/export files should be written to object storage and returned by reference.

---

# 26. Observability — planned production requirement

The codebase currently relies primarily on platform/application logs and persisted job errors. Production hardening should add:

- structured request/job logging;
- correlation/request IDs;
- duration metrics by operation/test/model;
- dataset-size distribution metrics without logging user data values;
- queue latency/retry metrics;
- worker failure rate;
- Blob transfer failures;
- DB pool/query failures;
- frontend error reporting;
- alerting for sustained failure rates.

Do not log raw dataset rows or sensitive cell values by default.

---

# 27. Data privacy considerations

The platform processes arbitrary user-supplied datasets and therefore must treat dataset contents as potentially sensitive even when the application does not know their semantic meaning.

Architecture rules:

- private object storage;
- least-privilege credentials;
- no raw row logging;
- bounded persisted error messages;
- authorization before issuing download/upload credentials;
- configurable lifecycle/deletion policy before production launch;
- explicit user deletion support before claiming durable privacy controls.

Retention/deletion policy is not implemented in the current product baseline and must be defined before production use with sensitive data.

---

# 28. Architecture decision record summary

## ADR-001 — Polyglot Next.js + Python

**Decision:** Next.js for UI/control route; Python/FastAPI for analytical backend.  
**Reason:** browser product development and scientific Python ecosystems have different strengths. The service boundary keeps both focused.

## ADR-002 — Canonical Parquet

**Decision:** normalize CSV/Parquet inputs to immutable canonical Parquet.  
**Reason:** consistent downstream execution, columnar analytics and provider-independent artifacts.

## ADR-003 — Immutable dataset versions

**Decision:** transformations create child versions.  
**Reason:** reproducibility, retry safety and explainable history.

## ADR-004 — Direct object upload

**Decision:** browser uploads datasets directly to object storage.  
**Reason:** serverless HTTP payload limits and avoidance of redundant data transfer.

## ADR-005 — DuckDB operation compiler

**Decision:** typed operation DSL compiled to DuckDB SQL.  
**Reason:** efficient tabular transformations while preventing arbitrary client SQL.

## ADR-006 — Durable jobs for mutation/heavy work

**Decision:** ingestion and transform apply are job-backed; read-only bounded analytics are interactive.  
**Reason:** mutation requires durable status/retry semantics; interactive exploration benefits from immediate responses.

## ADR-007 — Queue/storage provider abstractions

**Decision:** local and Vercel providers implement common contracts.  
**Reason:** testability, local parity and future provider migration.

## ADR-008 — Inference rejects oversized runs rather than sampling

**Decision:** interactive inferential statistics enforce an observation ceiling.  
**Reason:** hidden downsampling changes inferential meaning. Future large runs should move compute, not silently change the statistical dataset.

---

# 29. Rules for adding new features

## New Prepare operation

A new transform must:

1. add a typed Pydantic operation model;
2. preserve operation schema/versioning;
3. validate stable column IDs/types;
4. implement schema evolution;
5. compile safely to DuckDB SQL/parameters;
6. work in preview without durable mutation;
7. work in worker apply to a new canonical version;
8. add unit/integration tests;
9. update SRS/UI docs when user-visible.

## New Explore query/chart

A new Explore capability must:

1. be read-only;
2. bind to exact version;
3. validate variable types;
4. bound response size;
5. separate analytical payload from renderer;
6. provide tests;
7. document whether any sampling affects only visualization or underlying statistics.

## New inferential test

A new test must:

1. define compatible analytical goal/roles;
2. define null hypothesis and alternatives;
3. specify missing-value behavior;
4. provide statistic/p-value;
5. provide estimate/CI where meaningful;
6. provide effect size where meaningful;
7. expose assumptions/diagnostics;
8. avoid silent inferential sampling;
9. provide neutral interpretation;
10. include deterministic fixture tests.

## New deferred job family

A new job type must:

1. use a unique idempotency key;
2. persist complete execution configuration;
3. be safe under duplicate delivery;
4. use deterministic job-scoped artifact namespaces;
5. persist bounded errors;
6. return an existing output if already succeeded;
7. expose status to the frontend.

---

# 30. Known architecture gaps

The following gaps are intentional/currently unresolved and should not be hidden in implementation claims:

1. No production authentication/resource authorization model yet.
2. No persistent saved analysis-result resource yet.
3. No Model execution/resource layer yet.
4. No Results/report/export layer yet.
5. No user-driven deletion/retention lifecycle yet.
6. No production observability/alerting standard yet.
7. No benchmark-derived dataset size tiers beyond endpoint-specific bounds.
8. No external compute provider implemented yet; only the abstraction/upgrade path exists.
9. No dedicated cache layer for repeatedly materialized canonical artifacts.
10. The frontend currently centralizes substantial workflow state in `DataWorkspace`; this may require decomposition as Model/Results are added.

---

# 31. Related documentation

- [`SRS.md`](SRS.md) — normative product requirements and current/planned status.
- [`UI-UX-spec.md`](UI-UX-spec.md) — application shell, design tokens, workflow interactions and accessibility.
- [`serverless-architecture.md`](serverless-architecture.md) — dated Vercel research, limits and deployment rationale.
- [`../README.md`](../README.md) — repository entry point/local setup.

# Analytica Workbench

Analytica Workbench is a professional no-code/low-code data-analysis workbench for data preparation, exploration, statistical inference, predictive modeling, evaluation, and reproducible reporting.

## Current product state

The implemented workflow is:

`Data → Prepare → Explore → Analyze → Model → Results`

The Model workspace supports supervised regression/classification with durable training runs, baseline comparisons, and saved evaluations. Results stores analysis, chart, and model snapshots for each dataset version. It can assemble a printable HTML report and export CSV, Parquet, and SVG artifacts. Unsupervised modeling remains planned.

## Repository layout

```text
analytica-workbench/
├── frontend/   # Next.js + React web application
├── backend/    # FastAPI + Python analytics API
├── docs/       # Product, UI/UX and architecture source-of-truth
└── .github/    # CI workflows
```

## Documentation

- [`docs/SRS.md`](docs/SRS.md) — complete software requirements specification, implemented/planned status, functional requirements, non-functional requirements and V1 acceptance definition.
- [`docs/UI-UX-spec.md`](docs/UI-UX-spec.md) — visual language, design tokens, application shell, interaction rules, workflow behavior, accessibility and responsive specification.
- [`docs/architecture.md`](docs/architecture.md) — system decomposition, data/version model, backend layers, upload/ingestion/transform/model/result flows, persistence, queues, storage and security.
- [`docs/implementation-plan.md`](docs/implementation-plan.md) — phase-by-phase work and completion checks.
- [`docs/serverless-architecture.md`](docs/serverless-architecture.md) — dated Vercel platform research and serverless constraints used by the deployment architecture.

## Deployment model

This repository is structured as a Vercel monorepo with two independently deployable projects:

- `frontend/` — configure this directory as the Root Directory of the frontend Vercel project.
- `backend/` — configure this directory as the Root Directory of the Python API Vercel project.

The backend is intentionally stateless. User datasets upload directly from the browser to private object storage rather than being proxied through a Vercel Function. API requests carry dataset references and operation parameters, not large file bodies.

The current codebase does not yet implement complete production authentication/resource ownership. The frontend upload-signing route is therefore guarded in production until that security boundary is configured. See the SRS and architecture documents for the production-readiness requirements.

## Local development

Use Python 3.12 for the backend. Start it first:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app:app --reload
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The example configuration uses a development-only upload endpoint that writes to the backend's local artifact store. It lets the full CSV/Parquet flow run without Vercel Blob credentials. Production continues to use private direct-to-Blob uploads; the local endpoint returns 404 there. To exercise Blob locally instead, set `ANALYTICA_LOCAL_UPLOADS=false`, configure Blob credentials for both projects, and set the backend artifact store to `vercel_blob`.

The backend exposes versioned APIs under `/api/v1` and interactive OpenAPI documentation at `/docs`.

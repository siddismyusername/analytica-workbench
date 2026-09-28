# Analytica Workbench

Analytica Workbench is a professional no-code/low-code data-analysis workbench for data preparation, exploration, statistical inference, predictive modeling, evaluation, and reproducible reporting.

## Current product state

The implemented workflow is:

`Data → Prepare → Explore → Analyze`

`Model` and `Results` are defined in the project requirements and architecture but are not yet implemented.

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
- [`docs/architecture.md`](docs/architecture.md) — system decomposition, data/version model, backend layers, upload/ingestion/transform flows, persistence, queues, storage, security and planned Model/Results architecture.
- [`docs/serverless-architecture.md`](docs/serverless-architecture.md) — dated Vercel platform research and serverless constraints used by the deployment architecture.

## Deployment model

This repository is structured as a Vercel monorepo with two independently deployable projects:

- `frontend/` — configure this directory as the Root Directory of the frontend Vercel project.
- `backend/` — configure this directory as the Root Directory of the Python API Vercel project.

The backend is intentionally stateless. User datasets upload directly from the browser to private object storage rather than being proxied through a Vercel Function. API requests carry dataset references and operation parameters, not large file bodies.

The current codebase does not yet implement complete production authentication/resource ownership. The frontend upload-signing route is therefore guarded in production until that security boundary is configured. See the SRS and architecture documents for the production-readiness requirements.

## Local development

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

The backend exposes versioned APIs under `/api/v1` and interactive OpenAPI documentation at `/docs`.

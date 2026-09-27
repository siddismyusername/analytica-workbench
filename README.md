# Analytica Workbench

Analytica Workbench is a professional no-code/low-code data-analysis workbench for data preparation, exploration, statistical inference, predictive modeling, evaluation, and reproducible reporting.

## Repository layout

```text
analytica-workbench/
├── frontend/   # Next.js + React web application
├── backend/    # FastAPI + Python analytics API
├── docs/       # Product and architecture documentation
└── .github/    # CI workflows
```

## Deployment model

This repository is structured as a Vercel monorepo with two independently deployable projects:

- `frontend/` — configure this directory as the Root Directory of the frontend Vercel project.
- `backend/` — configure this directory as the Root Directory of the Python API Vercel project.

The backend is intentionally stateless. User datasets should be uploaded directly from the browser to object storage rather than proxied through a Vercel Function. API requests should carry dataset references and operation parameters, not large file bodies.

See [`docs/serverless-architecture.md`](docs/serverless-architecture.md) for the researched constraints and deployment rationale.

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

The backend exposes health and capability metadata under `/api/v1` and interactive OpenAPI documentation at `/docs`.

# Application architecture

Analytica Workbench is organized as a polyglot monorepo.

## Frontend

`frontend/` contains the Next.js application. Its responsibility is the professional analytical workspace: import flows, dataset tables, profiling views, operation configuration, analysis results, model evaluation, and report composition.

The visual architecture keeps high-density analytical content on solid surfaces while reserving translucent/glass materials for navigation and transient control chrome.

## Backend

`backend/` contains a FastAPI application running on Vercel's Python runtime. It is the execution boundary for statistical operations, transformations, model training, evaluation, and dataset metadata.

The backend is stateless by design. Durable datasets, generated artifacts, job state, and analysis provenance must live outside the function filesystem.

## Execution classes

Operations should be classified before implementation:

1. **Interactive** — bounded work that reliably completes inside an HTTP function request.
2. **Deferred** — expensive work submitted as a durable job and processed asynchronously.
3. **External compute** — workloads whose memory, CPU, duration, or specialized runtime requirements exceed the Vercel Function envelope.

This separation is intentional. The public API should use job/resource identifiers so a workload can move from interactive execution to a queue or external worker without changing the frontend's conceptual model.

## Data movement

Large dataset bytes should not transit through application functions. The browser uploads directly to private object storage, then the Python backend receives an authenticated object reference. Analysis outputs that exceed API response limits should likewise be written to object storage and returned by reference.

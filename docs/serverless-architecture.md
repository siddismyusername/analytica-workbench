# Serverless architecture research — Vercel

Research date: 2026-09-28.

This document records deployment facts used to structure the repository. It is intentionally limited to claims supported by Vercel's current documentation.

## Chosen topology

The repository uses two top-level applications, `frontend/` and `backend/`, deployed as separate Vercel projects from the same Git repository. Vercel documents this as a supported monorepo pattern: each directory can be imported as a separate project by selecting its Root Directory.

Source: https://vercel.com/docs/monorepos

Vercel also has a newer Services capability that can colocate Next.js and FastAPI under one project/domain, but as of the research date Services is Private Beta. The baseline architecture therefore does not depend on it.

Source: https://vercel.com/docs/services

## Python runtime

Vercel's Python runtime is Beta on all plans and supports FastAPI. Supported Python versions are currently 3.12, 3.13, and 3.14; 3.12 is the default. A FastAPI application is deployed as a Vercel Function running on Fluid compute.

Sources:
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/docs/frameworks/backend/fastapi

The backend therefore targets Python 3.12, which is supported by Vercel and by the current scientific-Python packages selected for the project.

## Request and response payloads

Vercel Functions cap both request and response payloads at 4.5 MB. Vercel explicitly recommends direct client uploads to Vercel Blob for files larger than that limit.

Sources:
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/vercel-blob/client-upload

Consequences for Analytica Workbench:

- Dataset uploads must not be proxied through FastAPI.
- The browser should upload directly to private object storage.
- FastAPI receives an object identifier/reference plus operation parameters.
- Large cleaned datasets, model artifacts, and bulky result tables should be persisted and returned by reference instead of embedded in an HTTP response.

## Memory and CPU

Vercel documents 2 GB / 1 vCPU as the default Function allocation. Pro and Enterprise projects can select 4 GB / 2 vCPUs; Hobby uses the default allocation.

Source: https://vercel.com/docs/functions/configuring-functions/memory

This is sufficient for many ordinary tabular analyses but is not an unlimited analytics environment. Dataset size and algorithm complexity must be bounded, measured, and surfaced to users before execution.

## Function duration

Fluid-compute Python functions default to five minutes. Vercel announced support for durations up to 30 minutes for Pro and Enterprise functions in June 2026, with durations above 800 seconds in beta and requiring Fluid compute.

Sources:
- https://vercel.com/docs/functions/limitations
- https://vercel.com/changelog/vercel-functions-can-now-run-up-to-30-minutes

The initial backend keeps HTTP work at a conservative 300-second ceiling. Long-running analysis should move to a durable job instead of holding an HTTP request open.

## Scientific Python bundle size

The standard documented Python Function bundle limit is 500 MB uncompressed. Vercel introduced Large Functions on Fluid compute in June 2026 with support for deployments up to 5 GB; new projects created after June 30, 2026 are automatically enrolled in that beta.

Sources:
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size

The analytics backend deliberately includes NumPy, pandas, SciPy, statsmodels, scikit-learn, and PyArrow. Bundle size must be monitored in CI/deployments rather than assumed to be harmless.

## Deferred execution

Vercel Queues is a durable event system intended for deferred expensive work, retries, and traffic absorption. Poll mode can also be consumed by workers outside Vercel.

Sources:
- https://vercel.com/docs/queues
- https://vercel.com/docs/queues/poll-mode

This gives the product an upgrade path: interactive operations can remain FastAPI requests, while expensive models or large transforms can become queued jobs. If Vercel's CPU/memory envelope is eventually insufficient, workers can move to dedicated compute while retaining the queue/API contract.

## Storage

Vercel Blob supports private object storage and multipart uploads; Vercel recommends multipart uploads for files larger than 100 MB.

Sources:
- https://vercel.com/docs/vercel-blob
- https://vercel.com/docs/vercel-blob/private-storage

No user dataset should rely on a Function's local filesystem for durable storage.

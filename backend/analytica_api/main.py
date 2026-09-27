import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analytica_api.routes.system import router as system_router


def _allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Analytica Workbench API",
        version="0.1.0",
        description="Stateless Python execution API for the Analytica Workbench.",
    )

    origins = _allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(system_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "analytica-workbench-api",
            "status": "ok",
            "docs": "/docs",
        }

    return app

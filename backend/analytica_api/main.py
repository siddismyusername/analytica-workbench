from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analytica_api.config import get_settings
from analytica_api.routes.operations import router as operations_router
from analytica_api.routes.system import router as system_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="Stateless analytical control API for the Analytica Workbench.",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(system_router, prefix="/api/v1")
    app.include_router(operations_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "analytica-workbench-api",
            "status": "ok",
            "docs": "/docs",
        }

    return app

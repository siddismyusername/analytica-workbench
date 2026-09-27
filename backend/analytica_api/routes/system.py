from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "analytica-workbench-api"}


@router.get("/capabilities")
async def capabilities() -> dict[str, object]:
    return {
        "execution": {
            "interactive": True,
            "deferred_jobs": "planned",
            "large_uploads": "direct-to-object-storage",
        },
        "analytics_stack": [
            "numpy",
            "pandas",
            "scipy",
            "statsmodels",
            "scikit-learn",
            "pyarrow",
        ],
        "formats": ["csv", "xlsx", "parquet"],
    }

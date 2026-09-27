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
            "canonical_dataset_format": "parquet",
        },
        "analytics_stack": [
            "duckdb",
            "pyarrow",
            "numpy",
            "pandas",
            "scipy",
            "statsmodels",
            "scikit-learn",
        ],
        "pipeline_schema_version": 1,
        "ingestion": {
            "implemented": ["csv", "parquet"],
            "planned": ["xlsx"],
        },
    }

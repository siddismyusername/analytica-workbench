from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Analytica Workbench API"
    environment: Literal["development", "test", "production"] = "development"
    cors_allowed_origins: str = "http://localhost:3000"
    duckdb_threads: int = Field(default=1, ge=1, le=64)
    database_url: str = "sqlite+pysqlite:///./analytica.db"
    artifact_store_backend: Literal["local", "vercel_blob"] = "local"
    local_artifact_root: str = ".analytica/artifacts"
    queue_provider: Literal["inline", "vercel"] = "inline"
    max_upload_bytes: int | None = Field(default=None, ge=1)

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

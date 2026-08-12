from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AutoAce Audio Analysis"
    app_env: Literal["development", "test", "production"] = "development"
    app_data_dir: Path = Path("var")
    database_path: Path | None = None

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_benchmark_model: str = "gemini-3-flash-preview"
    gemini_timeout_seconds: int = Field(default=300, ge=15, le=900)
    gemini_max_output_tokens: int = Field(default=384, ge=128, le=1024)
    gemini_max_retries: int = Field(default=2, ge=0, le=5)
    gemini_thinking_level: Literal["minimal", "low"] = "minimal"

    max_batch_files: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    max_batch_bytes: int = Field(default=250 * 1024 * 1024, ge=1024)
    max_archive_ratio: int = Field(default=100, ge=2, le=1000)
    processing_concurrency: int = Field(default=2, ge=1, le=8)
    long_silence_seconds: float = Field(default=10.0, ge=2.0, le=60.0)

    evaluator_username: str = "evaluator"
    evaluator_password: SecretStr = SecretStr("change-me-local")
    evaluator_password_hash: SecretStr | None = None
    session_secret: SecretStr = SecretStr("change-me-before-deploying")
    cookie_secure: bool = False
    trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "testserver"]
    session_max_age_seconds: int = Field(default=8 * 60 * 60, ge=300)

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.database_path is None:
            self.database_path = self.app_data_dir / "autoace.sqlite3"
        if self.app_env == "production":
            if self.session_secret.get_secret_value() == "change-me-before-deploying":
                raise ValueError("SESSION_SECRET must be changed in production")
            if (
                not self.evaluator_password_hash
                and self.evaluator_password.get_secret_value() == "change-me-local"
            ):
                raise ValueError("EVALUATOR_PASSWORD or EVALUATOR_PASSWORD_HASH must be set in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        return self

    @property
    def uploads_dir(self) -> Path:
        return self.app_data_dir / "uploads"

    @property
    def artifacts_dir(self) -> Path:
        return self.app_data_dir / "artifacts"

    def ensure_directories(self) -> None:
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

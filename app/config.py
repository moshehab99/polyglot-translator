"""Application settings loaded from the environment / ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["gemini", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: ProviderName = "gemini"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"

    max_chars: int = Field(default=5000, ge=1, le=50_000)
    request_timeout_s: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _require_active_provider_key(self) -> Settings:
        key = self.active_api_key
        if key is None or not key.get_secret_value().strip():
            env_var = f"{self.provider.upper()}_API_KEY"
            raise ValueError(
                f"PROVIDER={self.provider} but {env_var} is not set. "
                "Add it to your .env file (see .env.example)."
            )
        return self

    @property
    def active_api_key(self) -> SecretStr | None:
        if self.provider == "gemini":
            return self.gemini_api_key
        return self.anthropic_api_key

    @property
    def active_model(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        return self.anthropic_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

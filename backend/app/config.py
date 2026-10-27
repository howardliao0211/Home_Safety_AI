from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", ROOT / "backend/.env"), extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["local", "production"] = "local"
    model_provider: Literal["groq", "muse"] = "groq"
    groq_api_key: SecretStr | None = None
    groq_model: str = ""
    model_timeout_seconds: float = 90
    google_cloud_project: str = "home-safety-local"
    firestore_database_id: str = "(default)"
    firestore_emulator_host: str | None = None
    storage_emulator_host: str | None = None
    photos_bucket: str = "home-safety-local-photos"
    demo_bearer_token: SecretStr | None = None
    cors_origins: list[str] = []

    @model_validator(mode="after")
    def validate_environment(self):
        if not 1 <= self.model_timeout_seconds <= 120:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be between 1 and 120")
        if self.model_provider == "groq":
            if not self.groq_api_key or not self.groq_api_key.get_secret_value().strip():
                raise ValueError("GROQ_API_KEY is required for MODEL_PROVIDER=groq")
            if not self.groq_model.strip():
                raise ValueError("GROQ_MODEL is required for MODEL_PROVIDER=groq")
        if self.environment == "production":
            if self.firestore_emulator_host or self.storage_emulator_host:
                raise ValueError("Emulator endpoints are forbidden in production")
            if not self.demo_bearer_token or not self.demo_bearer_token.get_secret_value():
                raise ValueError("DEMO_BEARER_TOKEN is required in production")
        else:
            self.firestore_emulator_host = self.firestore_emulator_host or "127.0.0.1:8080"
            self.storage_emulator_host = self.storage_emulator_host or "http://127.0.0.1:4443"
            if not self.cors_origins:
                self.cors_origins = ["http://localhost:8081", "http://127.0.0.1:8081"]
        return self

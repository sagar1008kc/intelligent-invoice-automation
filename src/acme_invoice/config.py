"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    xai_model: str = Field(default="grok-3", alias="XAI_MODEL")
    inventory_db_path: Path = Field(default=ROOT_DIR / "inventory.db", alias="INVENTORY_DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    confidence_threshold: float = Field(default=0.7, alias="CONFIDENCE_THRESHOLD")
    approval_amount_threshold: float = Field(default=10000.0, alias="APPROVAL_AMOUNT_THRESHOLD")
    max_extraction_retries: int = Field(default=2, alias="MAX_EXTRACTION_RETRIES")
    price_anomaly_tolerance: float = Field(default=0.15, alias="PRICE_ANOMALY_TOLERANCE")

    @property
    def has_api_key(self) -> bool:
        return bool(self.xai_api_key and self.xai_api_key != "your_xai_api_key_here")


@lru_cache
def get_settings() -> Settings:
    return Settings()

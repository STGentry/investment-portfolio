"""Application configuration loaded from environment variables (.env)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _resolve_path(value: str, default: str) -> str:
    """Resolve a possibly-relative path against the project root."""
    raw = os.getenv(value) or default
    if os.path.isabs(raw):
        return raw
    return str(BASE_DIR / raw)


class Settings:
    """Runtime configuration."""

    DB_PATH: str = _resolve_path("DB_PATH", "portfolio.db")
    OLLAMA_API_URL: str = os.getenv("OLLAMA_API_URL", "")


settings = Settings()
"""
config.py
=========
Central configuration for the Field Audit Intelligence backend.

All runtime configuration is pulled from environment variables (with sane
defaults for local/demo use) so the exact same Docker image can be pointed at
different franchise brands, models, or data stores without a code change.

Why this matters for the business:
- On HF Spaces, secrets (API keys) are injected as environment variables via
  the Space's "Settings > Repository secrets" panel -- never hard-coded.
- Keeping every tunable knob in one place makes it obvious what a
  reviewer / new engineer needs to set up before the app will run for real.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory of the whole project (one level above /backend)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """
    Strongly-typed application settings.

    Every field can be overridden via an environment variable of the same
    (upper-cased) name, e.g. GROQ_API_KEY, GOOGLE_MAPS_API_KEY, etc.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider -------------------------------------------------
    # This POC talks to Groq (fast, cheap hosted inference for open-weight
    # models) -- a good fit for a public, free-to-run HF Spaces live demo.
    # All LLM calls go through Pydantic AI (backend/agents.py), so swapping
    # to a different provider later is a small, contained change.
    groq_api_key: str | None = None

    # Model tiering: a *smaller/faster* model handles simple
    # classification-style steps (clarification check, review
    # summarization) and a *larger* model handles judgment-heavy steps
    # (findings classification, franchisee-facing corrective actions).
    # This is a real cost/latency lever once an agent like this runs across
    # hundreds of locations doing several LLM calls per audit -- see the
    # written summary for the business rationale. Defaults are Groq's
    # current (mid-2026) general-purpose production-tier models.
    model_fast: str = os.getenv("BROADPEAK_MODEL_FAST", "llama-3.1-8b-instant")
    model_strong: str = os.getenv("BROADPEAK_MODEL_STRONG", "llama-3.3-70b-versatile")

    # --- Google Places -------------------------------------------------
    google_maps_api_key: str | None = None
    # If no key is configured, the app runs in MOCK REVIEW mode so the POC
    # is fully demoable without live credentials. This is clearly surfaced
    # in both the API responses and the UI -- never silently faked.
    google_places_base_url: str = "https://places.googleapis.com/v1"

    # --- Storage ---------------------------------------------------------
    sqlite_path: str = str(DATA_DIR / "audit_intelligence.db")
    chroma_path: str = str(DATA_DIR / "chroma")

    # --- Backend network ---------------------------------------------------
    backend_host: str = "127.0.0.1"
    backend_port: int = int(os.getenv("BACKEND_PORT", "8000"))
    backend_internal_url: str = os.getenv(
        "BACKEND_INTERNAL_URL", f"http://127.0.0.1:{os.getenv('BACKEND_PORT', '8000')}"
    )

    @property
    def reviews_are_mocked(self) -> bool:
        return not bool(self.google_maps_api_key)

    @property
    def llm_is_configured(self) -> bool:
        return bool(self.groq_api_key)


settings = Settings()

"""Runtime configuration, read from environment variables.

Every setting has a sensible default so the app runs fully offline with no
configuration. Override via env vars or a `.env` file loaded by your shell /
Docker Compose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
SAMPLE_DATA_DIR = ROOT_DIR / "data" / "sample"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- Intelligence layer -------------------------------------------------
    # auto | ollama | openai | heuristic
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "auto").lower())
    ollama_host: str = field(default_factory=lambda: _env("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.1"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    llm_timeout_s: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_S", 60.0))
    # Max tickets sent to the LLM for direct labelling; the rest are labelled
    # by k-NN label propagation in embedding space (keeps cost/latency bounded).
    llm_ticket_budget: int = field(default_factory=lambda: _env_int("LLM_TICKET_BUDGET", 240))
    llm_batch_size: int = field(default_factory=lambda: _env_int("LLM_BATCH_SIZE", 20))

    # --- Embeddings ---------------------------------------------------------
    # auto | sentence-transformers | tfidf
    embedding_backend: str = field(default_factory=lambda: _env("EMBEDDING_BACKEND", "auto").lower())
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    # Weight of the theme seed-lexicon features blended into embeddings for
    # guided clustering. Empty = auto (1.0 for TF-IDF, 0.5 for transformers).
    theme_seed_weight: float | None = field(
        default_factory=lambda: float(os.environ["THEME_SEED_WEIGHT"]) if os.getenv("THEME_SEED_WEIGHT") else None)

    # --- Data ---------------------------------------------------------------
    # synthetic | sample | <path to a folder of CSVs>
    data_source: str = field(default_factory=lambda: _env("DATA_SOURCE", "synthetic"))
    synthetic_seed: int = field(default_factory=lambda: _env_int("SYNTHETIC_SEED", 42))


def get_settings() -> Settings:
    return Settings()

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("EMBEDDING_BACKEND", "tfidf")

from datetime import date  # noqa: E402

from app.config import Settings  # noqa: E402
from app.ingest import from_synthetic  # noqa: E402
from app.synthetic import generate  # noqa: E402


@pytest.fixture(scope="session")
def synth():
    return generate(seed=7, as_of=date(2026, 8, 1))


@pytest.fixture(scope="session")
def dataset(synth):
    return from_synthetic(synth)


@pytest.fixture(scope="session")
def settings():
    return Settings(llm_provider="heuristic", embedding_backend="tfidf")


@pytest.fixture(scope="session")
def mined(dataset, settings):
    from app.mining import mine_feedback
    from app.nlp.llm import LLMClient

    return mine_feedback(dataset, LLMClient(settings), settings, seed=7)

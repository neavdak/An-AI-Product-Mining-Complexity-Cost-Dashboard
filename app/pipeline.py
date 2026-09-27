"""Pipeline orchestration + in-memory state.

The expensive NLP stage (embeddings, clustering, LLM labelling) runs once per
dataset in a background thread. The cheap financial / framework stage is
recomputed on every request so dashboard sliders respond instantly.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from . import engine
from .config import SAMPLE_DATA_DIR, Settings, get_settings
from .ingest import Dataset, from_synthetic, load_folder
from .memo import generate_memo
from .mining import FeedbackResult, mine_feedback
from .nlp.llm import LLMClient
from .synthetic import generate

log = logging.getLogger(__name__)


@dataclass
class PipelineState:
    status: str = "idle"  # idle | running | ready | error
    stage: str = ""
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    dataset: Dataset | None = None
    feedback: FeedbackResult | None = None
    llm: LLMClient | None = None
    memo_cache: dict = field(default_factory=dict)
    version: int = 0


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.state = PipelineState()
        self._lock = threading.Lock()
        self._compute_cache: dict[tuple, tuple[pd.DataFrame, dict]] = {}

    # --------------------------------------------------------------- loading
    def default_dataset(self) -> Dataset:
        src = self.settings.data_source
        if src == "synthetic":
            return from_synthetic(generate(seed=self.settings.synthetic_seed))
        if src == "sample":
            return load_folder(SAMPLE_DATA_DIR, name="Sample dataset")
        return load_folder(src)

    def run(self, dataset: Dataset, background: bool = True) -> None:
        with self._lock:
            if self.state.status == "running":
                raise RuntimeError("A pipeline run is already in progress")
            self.state.status, self.state.stage, self.state.error = "running", "Starting", None
            self.state.started_at, self.state.finished_at = time.time(), None
        if background:
            threading.Thread(target=self._run, args=(dataset,), daemon=True).start()
        else:
            self._run(dataset)

    def _run(self, dataset: Dataset) -> None:
        st = self.state
        try:
            st.stage = "Connecting to intelligence layer"
            llm = LLMClient(self.settings)
            st.stage = f"Mining {len(dataset.feedback)} feedback items ({llm.provider})"
            fb = mine_feedback(dataset, llm, self.settings, seed=self.settings.synthetic_seed)
            with self._lock:
                st.dataset, st.feedback, st.llm = dataset, fb, llm
                st.memo_cache = {}
                self._compute_cache = {}
                st.version += 1
                st.status, st.stage, st.finished_at = "ready", "Done", time.time()
            log.info("Pipeline ready in %.1fs", st.finished_at - st.started_at)
        except Exception as exc:  # noqa: BLE001
            log.error("Pipeline failed: %s\n%s", exc, traceback.format_exc())
            st.status, st.error, st.finished_at = "error", str(exc), time.time()

    # --------------------------------------------------------------- queries
    def require_ready(self) -> PipelineState:
        if self.state.status != "ready" and self.state.dataset is None:
            raise RuntimeError(f"Pipeline not ready (status: {self.state.status})")
        return self.state

    def analysis(self, params: engine.ModelParams) -> tuple[pd.DataFrame, dict]:
        st = self.require_ready()
        key = (st.version, json.dumps(params.model_dump(), sort_keys=True))
        if key not in self._compute_cache:
            df = engine.compute(st.dataset, st.feedback.per_feature, params)
            summary = engine.portfolio_summary(df, params)
            if len(self._compute_cache) > 64:
                self._compute_cache.clear()
            self._compute_cache[key] = (df, summary)
        return self._compute_cache[key]

    def memo(self, params: engine.ModelParams) -> dict:
        st = self.require_ready()
        df, summary = self.analysis(params)
        key = (st.version, json.dumps(params.model_dump(), sort_keys=True))
        if key not in st.memo_cache:
            text, source = generate_memo(st.llm, df, summary, st.feedback.clusters)
            st.memo_cache[key] = {"markdown": text, "source": source}
        return st.memo_cache[key]

    def status(self) -> dict:
        st = self.state
        return {
            "status": st.status,
            "stage": st.stage,
            "error": st.error,
            "version": st.version,
            "elapsed_s": round((st.finished_at or time.time()) - st.started_at, 1) if st.started_at else None,
            "dataset": st.dataset.summary() if st.dataset else None,
            "nlp": st.feedback.meta if st.feedback else None,
            "llm": st.llm.info() if st.llm else None,
            "config": {
                "llm_provider_setting": self.settings.llm_provider,
                "ollama_host": self.settings.ollama_host,
                "ollama_model": self.settings.ollama_model,
                "openai_model": self.settings.openai_model if self.settings.openai_api_key else None,
                "embedding_backend_setting": self.settings.embedding_backend,
                "llm_ticket_budget": self.settings.llm_ticket_budget,
            },
        }


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline()

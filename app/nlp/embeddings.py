"""Text embeddings + vector index with graceful degradation.

Preferred: sentence-transformers (semantic embeddings) + FAISS (vector index).
Fallback:  TF-IDF -> TruncatedSVD (Latent Semantic Analysis) + NumPy cosine
           search. The fallback needs no model download and runs anywhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

log = logging.getLogger(__name__)

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS  # noqa: E402

_STOP = sorted(ENGLISH_STOP_WORDS | {"feature"})


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


@dataclass
class EmbeddingResult:
    vectors: np.ndarray  # L2-normalised, shape (n, d)
    backend: str
    model: str


class Embedder:
    def __init__(self, backend: str = "auto", model: str = "all-MiniLM-L6-v2", random_state: int = 42):
        self.requested = backend
        self.model_name = model
        self.random_state = random_state
        self._st_model = None
        self._tfidf: TfidfVectorizer | None = None
        self._svd: TruncatedSVD | None = None
        self.backend = self._resolve(backend)

    def _resolve(self, backend: str) -> str:
        if backend in ("auto", "sentence-transformers") and _has_module("sentence_transformers"):
            try:
                from sentence_transformers import SentenceTransformer

                self._st_model = SentenceTransformer(self.model_name)
                return "sentence-transformers"
            except Exception as exc:  # noqa: BLE001 - offline / download failure
                log.warning("sentence-transformers unavailable (%s); falling back to TF-IDF/LSA", exc)
        return "tfidf-lsa"

    def fit_transform(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(np.zeros((0, 1)), self.backend, self.model_name)
        if self.backend == "sentence-transformers":
            vecs = self._st_model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
            return EmbeddingResult(np.asarray(vecs, dtype=np.float32), self.backend, self.model_name)

        self._tfidf = TfidfVectorizer(ngram_range=(1, 1), min_df=2 if len(texts) > 50 else 1,
                                      sublinear_tf=True, stop_words=_STOP, max_features=20_000)
        X = self._tfidf.fit_transform(texts)
        n_comp = max(2, min(40, X.shape[1] - 1, X.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=n_comp, random_state=self.random_state)
        vecs = normalize(self._svd.fit_transform(X))
        return EmbeddingResult(vecs.astype(np.float32), self.backend, f"tfidf+svd({n_comp})")

    def transform(self, texts: list[str]) -> np.ndarray:
        if self.backend == "sentence-transformers":
            return np.asarray(self._st_model.encode(texts, normalize_embeddings=True), dtype=np.float32)
        if self._tfidf is None or self._svd is None:
            raise RuntimeError("fit_transform must be called first")
        return normalize(self._svd.transform(self._tfidf.transform(texts))).astype(np.float32)


class VectorIndex:
    """Cosine-similarity nearest-neighbour index (FAISS if installed)."""

    def __init__(self, vectors: np.ndarray):
        self.vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        self.backend = "numpy"
        self._faiss = None
        if _has_module("faiss") and len(self.vectors):
            try:
                import faiss

                self._faiss = faiss.IndexFlatIP(self.vectors.shape[1])
                self._faiss.add(self.vectors)
                self.backend = "faiss"
            except Exception as exc:  # noqa: BLE001
                log.warning("FAISS init failed (%s); using NumPy search", exc)

    def search(self, queries: np.ndarray, k: int = 5) -> tuple[np.ndarray, np.ndarray]:
        q = np.ascontiguousarray(queries, dtype=np.float32)
        k = min(k, len(self.vectors))
        if self._faiss is not None:
            return self._faiss.search(q, k)
        sims = q @ self.vectors.T
        idx = np.argsort(-sims, axis=1)[:, :k]
        return np.take_along_axis(sims, idx, axis=1), idx

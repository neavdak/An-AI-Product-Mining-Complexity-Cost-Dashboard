"""Semantic clustering of feedback + class-based TF-IDF keyword extraction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import silhouette_score

EXTRA_STOP = {"feature", "team", "product", "use", "just", "really", "does", "did", "don", "doesn",
              "ve", "ll", "sales", "reps", "admins", "finance", "managers", "revops", "success",
              "customer", "marketing", "inside", "account", "manager", "raised", "update", "advise"}


@dataclass
class ClusteringResult:
    labels: np.ndarray
    k: int
    silhouette: float
    centroids: np.ndarray
    keywords: dict[int, list[str]]
    representatives: dict[int, list[int]]  # cluster -> row indices closest to centroid
    k_scores: dict[int, float]


def choose_k(vectors: np.ndarray, k_min: int = 6, k_max: int = 16, random_state: int = 42) -> tuple[int, dict[int, float]]:
    n = len(vectors)
    k_max = max(2, min(k_max, n // 12 if n >= 36 else max(2, n // 3)))
    k_min = max(2, min(k_min, k_max))
    rng = np.random.default_rng(random_state)
    sample = vectors if n <= 2500 else vectors[rng.choice(n, 2500, replace=False)]
    scores: dict[int, float] = {}
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, n_init=4, random_state=random_state).fit(sample)
        if len(set(km.labels_)) < 2:
            continue
        scores[k] = float(silhouette_score(sample, km.labels_, metric="cosine"))
    if not scores:
        return k_min, {}
    best = max(scores.values())
    # Prefer the smallest k within 2% of the best score (parsimony).
    k = min(k for k, s in scores.items() if s >= best - 0.02)
    return k, scores


def ctfidf_keywords(texts: list[str], labels: np.ndarray, top_n: int = 6) -> dict[int, list[str]]:
    clusters = sorted(set(int(x) for x in labels))
    docs = [" ".join(t for t, lab in zip(texts, labels) if lab == c) for c in clusters]
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    cv = CountVectorizer(ngram_range=(1, 2), stop_words=list(ENGLISH_STOP_WORDS | EXTRA_STOP), min_df=1)
    tf = cv.fit_transform(docs).toarray().astype(float)
    tf_norm = tf / np.maximum(tf.sum(axis=1, keepdims=True), 1)
    avg_words = tf.sum() / max(len(clusters), 1)
    idf = np.log(1 + avg_words / np.maximum(tf.sum(axis=0), 1))
    scores = tf_norm * idf
    vocab = np.array(cv.get_feature_names_out())
    out: dict[int, list[str]] = {}
    for i, c in enumerate(clusters):
        ranked = vocab[np.argsort(-scores[i])]
        picked: list[str] = []
        for term in ranked:
            if any(term in p or p in term for p in picked):
                continue
            picked.append(str(term))
            if len(picked) == top_n:
                break
        out[c] = picked
    return out


def cluster(vectors: np.ndarray, texts_for_keywords: list[str], k: int | None = None,
            random_state: int = 42) -> ClusteringResult:
    n = len(vectors)
    if n < 4:
        labels = np.zeros(n, dtype=int)
        return ClusteringResult(labels, 1, 0.0, vectors.mean(axis=0, keepdims=True) if n else vectors,
                                {0: []}, {0: list(range(n))}, {})
    k_scores: dict[int, float] = {}
    if k is None:
        k, k_scores = choose_k(vectors, random_state=random_state)
    km = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit(vectors)
    labels = km.labels_.astype(int)
    sil = float(silhouette_score(vectors, labels, metric="cosine")) if k > 1 else 0.0
    keywords = ctfidf_keywords(texts_for_keywords, labels)
    reps: dict[int, list[int]] = {}
    for c in range(k):
        idx = np.where(labels == c)[0]
        d = np.linalg.norm(vectors[idx] - km.cluster_centers_[c], axis=1)
        reps[c] = [int(i) for i in idx[np.argsort(d)][:10]]
    return ClusteringResult(labels, k, sil, km.cluster_centers_, keywords, reps, k_scores)

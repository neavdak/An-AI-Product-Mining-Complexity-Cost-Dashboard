"""Module 2 - LLM-powered unstructured feedback mining.

Pipeline
    clean text -> attribute un-tagged tickets to features -> mask entity names
    -> embed (sentence-transformers | TF-IDF/LSA) -> choose k by silhouette
    -> KMeans clusters + c-TF-IDF keywords -> LLM labels a stratified sample
    (structured JSON) -> k-NN label propagation to the rest -> LLM names each
    cluster theme -> per-feature feedback aggregates.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.preprocessing import normalize

from .config import Settings
from .ingest import Dataset
from .nlp import classify as H
from .nlp.clustering import cluster as run_clustering
from .nlp.embeddings import Embedder, VectorIndex
from .nlp.llm import LLMClient
from .nlp.text import build_entity_masker, clean

log = logging.getLogger(__name__)
CATEGORIES = H.CATEGORIES

# Generic SaaS feedback theme lexicon used to name clusters when no LLM is available.
THEMES: list[tuple[str, str, str]] = [
    ("Slow load times", "Performance Issue", r"slow|load(ing)? time|spinning|sluggish|forever|ages|lag"),
    ("Crashes & errors", "Performance Issue", r"crash|error|froze|freeze|refresh|lost our work"),
    ("Sync failures", "Performance Issue", r"sync|stale|duplicated|out of date"),
    ("Timeouts on large data", "Performance Issue", r"time[sd]? ?out|timeout|large|records"),
    ("Confusing navigation", "UX Friction", r"confus|unintuitive|lost|navigation|find"),
    ("Too many clicks", "UX Friction", r"click|steps|clunky|one step"),
    ("Docs & onboarding gaps", "UX Friction", r"doc|onboard|training|tutorial|help articles"),
    ("Broken mobile layout", "UX Friction", r"layout|mobile|screen|tablet|responsive|overlap|cut off"),
    ("Unused features", "Feature Bloat Indicator", r"nobody|never used|don'?t know anyone|irrelevant|not sure what"),
    ("Interface clutter", "Feature Bloat Indicator", r"clutter|bloat|noise|busy"),
    ("Redundant with other tools", "Feature Bloat Indicator", r"redundant|duplicate|overlap|same thing|instead"),
    ("Requests to disable / remove", "Feature Bloat Indicator", r"disable|turn off|switch off|remove|paying for"),
    ("Time savings", "Core Utility", r"sav|time saver|less time|cut our|hours"),
    ("Mission-critical workflows", "Core Utility", r"essential|rely|critical|core to|renew|imagine"),
    ("Praise & reliability", "Core Utility", r"reliab|just works|great|fantastic|happy|best part|valuable"),
    ("Expansion requests", "Core Utility", r"would love|extend|add|support|perfect"),
]
IMPACT_TEMPLATES = {
    "Performance Issue": "Reliability defects drive support load and unplanned engineering hours - a direct complexity cost.",
    "UX Friction": "Usability friction depresses adoption and inflates onboarding / support cost per seat.",
    "Feature Bloat Indicator": "Customers signal low perceived value - candidate surface area to sunset or consolidate.",
    "Core Utility": "Validated value driver - protects retention and supports pricing power / upsell.",
}


@dataclass
class FeedbackResult:
    tickets: pd.DataFrame
    clusters: list[dict]
    per_feature: pd.DataFrame
    meta: dict = field(default_factory=dict)


def _heuristic_cluster_name(texts: list[str], keywords: list[str], dominant_cat: str) -> tuple[str, str]:
    blob = " ".join(texts).lower()
    scored = [(len(re.findall(pattern, blob)), name, cat) for name, cat, pattern in THEMES]
    # Prefer themes consistent with the cluster's dominant category.
    for pool in ([x for x in scored if x[2] == dominant_cat], scored):
        pool = [x for x in pool if x[0] > 0]
        if pool:
            _, name, cat = max(pool)
            return name, cat
    return (" / ".join(k.title() for k in keywords[:3]) or "Miscellaneous"), dominant_cat


def _projection(vectors: np.ndarray, seed: int = 42) -> np.ndarray:
    n = len(vectors)
    if n < 5:
        return np.zeros((n, 2))
    try:
        from sklearn.manifold import TSNE

        if n <= 4000:
            return TSNE(n_components=2, init="pca", perplexity=min(35, max(5, n // 20)),
                        random_state=seed, max_iter=600).fit_transform(vectors)
    except Exception as exc:  # noqa: BLE001
        log.warning("t-SNE failed (%s); falling back to PCA", exc)
    from sklearn.decomposition import PCA

    return PCA(n_components=2, random_state=seed).fit_transform(vectors)


def mine_feedback(ds: Dataset, llm: LLMClient, settings: Settings, seed: int = 42) -> FeedbackResult:
    t0 = time.time()
    fb = ds.feedback.copy()
    features = ds.features
    name_by_id = dict(zip(features["feature_id"], features["feature_name"]))
    empty_pf = pd.DataFrame(columns=["feature_id", "tickets", "tickets_per_month", "avg_sentiment", "friction_tickets",
                                     "friction_per_month", "bloat_share", "top_theme"] + CATEGORIES)
    keep = ["ticket_id", "feature_id", "feature_name", "attribution", "source", "created_at", "customer_tier",
            "text", "category", "category_confidence", "label_source", "sentiment", "summary",
            "cluster_id", "cluster_name", "x", "y"]
    if fb.empty:
        return FeedbackResult(pd.DataFrame(columns=keep), [], empty_pf,
                              {"n_tickets": 0, "n_clusters": 0, "silhouette": 0.0, "k_scores": {},
                               "embedding_backend": "–", "embedding_model": "–", "vector_index": "–",
                               "llm": llm.info(), "llm_heuristic_agreement": None, "label_sources": {},
                               "attribution": {}, "category_counts": {}, "elapsed_s": 0.0})

    fb["clean_text"] = fb["text"].map(clean)

    # --- 1. feature attribution for untagged tickets
    missing = fb["feature_id"] == ""
    fb["attribution"] = np.where(missing, "inferred", "provided")
    if missing.any():
        guesses = H.attribute_features(fb.loc[missing, "clean_text"].tolist(), list(name_by_id.items()))
        fb.loc[missing, "feature_id"] = guesses
        fb.loc[missing & (fb["feature_id"] == ""), "attribution"] = "unattributed"
    fb["feature_name"] = fb["feature_id"].map(name_by_id).fillna("Platform / Unattributed")

    # --- 2. embeddings on entity-masked text
    masker = build_entity_masker(features["feature_name"].tolist())
    masked = [masker(t) for t in fb["clean_text"]]
    embedder = Embedder(settings.embedding_backend, settings.embedding_model, random_state=seed)
    emb = embedder.fit_transform(masked)
    # Guided clustering: blend the semantic embedding with a SaaS feedback-theme
    # seed lexicon (similar to seeded / guided topic modelling). Weight 0 disables.
    seed_w = settings.theme_seed_weight
    if seed_w is None:
        seed_w = 1.0 if emb.backend == "tfidf-lsa" else 0.5
    if seed_w > 0:
        theme_rx = [re.compile(p, re.IGNORECASE) for _, _, p in THEMES]
        concept = np.array([[len(rx.findall(t)) for rx in theme_rx] for t in masked], dtype=np.float32)
        vectors = normalize(np.hstack([emb.vectors, seed_w * normalize(concept)])).astype(np.float32)
    else:
        vectors = emb.vectors
    index = VectorIndex(vectors)

    # --- 3. clustering
    cres = run_clustering(vectors, masked, random_state=seed)
    fb["cluster_id"] = cres.labels

    # --- 4. classification: heuristic baseline for all rows
    heur = [H.classify_text(t) for t in fb["clean_text"]]
    fb["heuristic_category"] = [c for c, _ in heur]
    fb["category"] = fb["heuristic_category"]
    fb["category_confidence"] = [conf for _, conf in heur]
    fb["label_source"] = "heuristic"
    fb["summary"] = ""
    llm_sentiment: dict[int, float] = {}
    agreement = None

    if llm.enabled:
        budget = min(settings.llm_ticket_budget, len(fb))
        rng = np.random.default_rng(seed)
        # stratified sample: proportional per cluster, representatives first
        sample: list[int] = []
        for c in range(cres.k):
            members = np.where(cres.labels == c)[0]
            quota = max(2, int(round(budget * len(members) / len(fb))))
            reps = [i for i in cres.representatives.get(c, []) if i in set(members)][: quota // 2]
            rest = [i for i in rng.permutation(members) if i not in reps][: quota - len(reps)]
            sample.extend(reps + rest)
        sample = sample[:budget]
        known: dict[int, str] = {}
        bs = max(1, settings.llm_batch_size)
        for b in range(0, len(sample), bs):
            chunk = sample[b:b + bs]
            res = llm.classify_batch([(str(i), fb.at[i, "clean_text"]) for i in chunk])
            for i in chunk:
                r = res.get(str(i))
                if r:
                    known[i] = r["category"]
                    llm_sentiment[i] = r["sentiment"]
                    fb.at[i, "summary"] = r["summary"]
        if known:
            agreement = float(np.mean([fb.at[i, "heuristic_category"] == c for i, c in known.items()]))
            labels, conf = H.propagate_labels(vectors, known)
            fb["category"] = labels
            fb["category_confidence"] = conf
            fb["label_source"] = ["llm" if i in known else "propagated" for i in range(len(fb))]

    fb["sentiment"] = [llm_sentiment.get(i, H.sentiment(t, c))
                       for i, (t, c) in enumerate(zip(fb["clean_text"], fb["category"]))]
    fb["sentiment"] = fb["sentiment"].round(3)

    # --- 5. name clusters
    clusters: list[dict] = []
    used_names: set[str] = set()
    for c in range(cres.k):
        members = fb[fb["cluster_id"] == c]
        if members.empty:
            continue
        mix = members["category"].value_counts(normalize=True)
        dominant = str(mix.index[0])
        rep_idx = cres.representatives.get(c, [])[:8]
        quotes_masked = [masked[i] for i in rep_idx]
        name, cat = _heuristic_cluster_name([masked[i] for i in members.index], cres.keywords.get(c, []), dominant)
        if name in used_names:  # disambiguate duplicate theme names with a distinctive keyword
            extra = next((k for k in cres.keywords.get(c, []) if k.lower() not in name.lower()), str(c))
            name = f"{name} · {extra}"
        used_names.add(name)
        top_feats = members[members["feature_id"] != ""]["feature_id"].value_counts().head(5)
        info = {
            "cluster_id": int(c),
            "name": name,
            "category": dominant,
            "summary": (f"{len(members)} tickets ({len(members) / len(fb):.0%} of feedback) across "
                        f"{members['feature_id'].nunique()} features; most affected: "
                        + ", ".join(name_by_id.get(f, f) for f in top_feats.index[:3]) + "."),
            "business_impact": IMPACT_TEMPLATES.get(dominant, ""),
            "label_source": "heuristic",
        }
        if llm.enabled:
            named = llm.name_cluster(cres.keywords.get(c, []), quotes_masked)
            if named:
                info.update({k: v for k, v in named.items() if v})
                info["label_source"] = "llm"
        clusters.append({
            **info,
            "size": int(len(members)),
            "share": round(len(members) / len(fb), 4),
            "keywords": cres.keywords.get(c, []),
            "avg_sentiment": round(float(members["sentiment"].mean()), 3),
            "category_mix": {k: round(float(v), 3) for k, v in mix.items()},
            "top_features": [{"feature_id": f, "feature_name": name_by_id.get(f, f), "count": int(n)}
                             for f, n in top_feats.items()],
            "quotes": [fb.at[i, "clean_text"] for i in rep_idx[:4]],
        })
    cname = {cl["cluster_id"]: cl["name"] for cl in clusters}
    fb["cluster_name"] = fb["cluster_id"].map(cname)
    clusters.sort(key=lambda x: -x["size"])

    # --- 6. 2-D semantic map
    xy = _projection(vectors, seed)
    fb["x"], fb["y"] = np.round(xy[:, 0], 3), np.round(xy[:, 1], 3)

    # --- 7. per-feature aggregates
    dates = pd.to_datetime(fb["created_at"], errors="coerce")
    window_months = max(1.0, ((dates.max() - dates.min()).days / 30.4) if dates.notna().any() else 12.0)
    release = pd.to_datetime(features.set_index("feature_id")["release_date"], errors="coerce")
    end = dates.max() if dates.notna().any() else pd.Timestamp.today()
    attributed = fb[fb["feature_id"] != ""]
    counts = pd.crosstab(attributed["feature_id"], attributed["category"]).reindex(columns=CATEGORIES, fill_value=0)
    pf = counts.copy()
    pf["tickets"] = counts.sum(axis=1)
    pf["avg_sentiment"] = attributed.groupby("feature_id")["sentiment"].mean().round(3)
    pf["top_theme"] = attributed.groupby("feature_id")["cluster_name"].agg(lambda s: s.value_counts().index[0])
    pf = pf.reset_index().rename(columns={"index": "feature_id"})
    age_m = pf["feature_id"].map(lambda f: ((end - release.get(f)).days / 30.4) if pd.notna(release.get(f)) else window_months)
    months_obs = np.clip(np.minimum(age_m.astype(float), window_months), 1.0, None)
    pf["tickets_per_month"] = (pf["tickets"] / months_obs).round(2)
    pf["friction_tickets"] = pf["UX Friction"] + pf["Performance Issue"]
    pf["friction_per_month"] = (pf["friction_tickets"] / months_obs).round(2)
    pf["bloat_share"] = (pf["Feature Bloat Indicator"] / pf["tickets"].clip(lower=1)).round(3)

    meta = {
        "n_tickets": int(len(fb)),
        "n_clusters": int(cres.k),
        "silhouette": round(cres.silhouette, 3),
        "k_scores": {int(k): round(v, 3) for k, v in cres.k_scores.items()},
        "embedding_backend": emb.backend,
        "embedding_model": emb.model,
        "theme_seed_weight": seed_w,
        "vector_index": index.backend,
        "llm": llm.info(),
        "llm_heuristic_agreement": round(agreement, 3) if agreement is not None else None,
        "label_sources": fb["label_source"].value_counts().to_dict(),
        "attribution": fb["attribution"].value_counts().to_dict(),
        "category_counts": fb["category"].value_counts().to_dict(),
        "elapsed_s": round(time.time() - t0, 2),
    }
    return FeedbackResult(fb[keep], clusters, pf, meta)

"""Offline (no-LLM) feedback classification, sentiment and feature attribution.

These heuristics serve three purposes:
  1. A fully offline fallback so the dashboard works without any LLM.
  2. A per-item safety net when an LLM returns malformed / invalid JSON.
  3. A baseline to benchmark LLM labelling quality against.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np

CATEGORIES = ["Core Utility", "UX Friction", "Performance Issue", "Feature Bloat Indicator"]

# (regex, weight) per category. Weighted keyword evidence, summed.
LEXICON: dict[str, list[tuple[str, float]]] = {
    "Performance Issue": [
        (r"\bslow(ly|er)?\b", 2), (r"\blag(s|gy|ging)?\b", 2), (r"time[sd]? ?out|timeout", 2.5),
        (r"\bcrash(es|ed|ing)?\b", 2.5), (r"\bfr(oze|eeze|eezes)\b", 2), (r"error|500\b|exception", 2),
        (r"take[s]? (forever|ages)|spinning|sluggish|render", 1.5), (r"\bsync(ing|ed)?\b", 1),
        (r"fail(ed|s|ure)?|not syncing|stale|missing|duplicated", 1.5), (r"load(ing)? (time|slow)|load times", 1.5),
        (r"refresh|lost our work|outage|downtime|latency", 1.2), (r"\bbug(s|gy)?\b|broken(?! on)", 1),
    ],
    "UX Friction": [
        (r"confus(ing|ed)|unintuitive|makes no sense|getting lost", 2.5), (r"can'?t figure|hard to (find|read|use)", 2.2),
        (r"too many (clicks|steps)|clicks|steps", 2), (r"clunky|awkward|cumbersome", 2),
        (r"documentation|docs|help articles|tutorial|onboarding|training", 2),
        (r"layout|responsive|overlap|cut off|small(er)? screens?|tablet|mobile", 1.5),
        (r"navigation|menus?|where to find|settings", 1), (r"\bui\b|\bux\b|design", 1),
    ],
    "Feature Bloat Indicator": [
        (r"nobody (on our team )?uses|never used|don'?t (use|know anyone)|not sure what it is for", 3),
        (r"irrelevant|unnecessary|redundant|duplicates?|overlaps?|same thing", 2.5),
        (r"clutter(s|ed)?|bloat(ed)?|noise|distracting", 2.5),
        (r"disable|turn off|switch off|remove|hide it|opt out", 2.5),
        (r"paying for features|we use .+ instead", 2), (r"why do we have", 1.5),
    ],
    "Core Utility": [
        (r"\blove\b|fantastic|great|excellent|best part|happy with", 2), (r"essential|critical|core to|rely on|can'?t imagine", 2.5),
        (r"saves?|time saver|cut our|less time|hours every", 2.2), (r"reliabl[ey]|just works|works well|valuable", 2),
        (r"would love|please (extend|add)|could you add|adding .+ would|also support", 2),
        (r"renew(ed|al)?|every day|daily|heavily", 1.5),
    ],
}
_COMPILED = {c: [(re.compile(p, re.IGNORECASE), w) for p, w in pats] for c, pats in LEXICON.items()}

POSITIVE = re.compile(r"\b(love|great|fantastic|excellent|best|happy|reliable|valuable|saves?|essential|perfect|"
                      r"works well|just works|time saver|solid|helpful|thanks)\b", re.IGNORECASE)
NEGATIVE = re.compile(r"\b(slow|crash\w*|error|froze|fail\w*|broken|confusing|clunky|lost|painful\w*|"
                      r"timeout|times out|blocking|clutter\w*|bloat\w*|irrelevant|redundant|unnecessary|"
                      r"distracting|nobody|never|stale|missing|outdated|hard|worse|lag\w*|sluggish|forever)\b",
                      re.IGNORECASE)


def score_categories(text: str) -> dict[str, float]:
    return {c: sum(w for rx, w in pats if rx.search(text)) for c, pats in _COMPILED.items()}


def classify_text(text: str) -> tuple[str, float]:
    """Return (category, confidence 0..1)."""
    scores = score_categories(text)
    total = sum(scores.values())
    if total == 0:
        return "UX Friction", 0.25  # unknown complaint - most common neutral bucket
    best = max(scores, key=scores.get)
    return best, round(scores[best] / total, 3)


def sentiment(text: str, category: str | None = None) -> float:
    pos = len(POSITIVE.findall(text))
    neg = len(NEGATIVE.findall(text))
    prior = {"Core Utility": 0.45, "UX Friction": -0.3, "Performance Issue": -0.45,
             "Feature Bloat Indicator": -0.35}.get(category or "", 0.0)
    raw = (pos - neg) / (pos + neg + 1)
    return float(np.clip(0.6 * raw + prior, -1, 1))


def propagate_labels(vectors: np.ndarray, known: dict[int, str], k: int = 7) -> tuple[list[str], list[float]]:
    """k-NN label propagation: label every row from its nearest labelled neighbours."""
    n = len(vectors)
    labels: list[str] = [""] * n
    conf: list[float] = [0.0] * n
    if not known:
        return labels, conf
    idx = np.array(sorted(known))
    lab = np.array([known[i] for i in idx])
    sims = vectors @ vectors[idx].T
    kk = min(k, len(idx))
    for row in range(n):
        if row in known:
            labels[row], conf[row] = known[row], 1.0
            continue
        nn = np.argpartition(-sims[row], kk - 1)[:kk]
        votes: Counter = Counter()
        for j in nn:
            votes[lab[j]] += max(float(sims[row, j]), 0.0) + 1e-6
        best, w = votes.most_common(1)[0]
        labels[row], conf[row] = best, round(w / sum(votes.values()), 3)
    return labels, conf


def attribute_features(texts: list[str], features: list[tuple[str, str]]) -> list[str]:
    """Map free text -> feature_id by (longest) name mention, then token overlap.

    `features` is a list of (feature_id, feature_name). Returns '' when no
    confident match (treated as a platform-level ticket).
    """
    by_len = sorted(features, key=lambda x: len(x[1]), reverse=True)
    token_sets = [(fid, {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 2}) for fid, name in features]
    out = []
    for text in texts:
        low = text.lower()
        hit = next((fid for fid, name in by_len if name.lower() in low), "")
        if not hit:
            toks = set(re.findall(r"[a-z0-9]+", low))
            best, best_score = "", 0.0
            for fid, ts in token_sets:
                if not ts:
                    continue
                s = len(ts & toks) / len(ts)
                if s > best_score:
                    best, best_score = fid, s
            hit = best if best_score >= 0.67 else ""
        out.append(hit)
    return out

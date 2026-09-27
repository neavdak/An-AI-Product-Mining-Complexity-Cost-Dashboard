import numpy as np
from sklearn.metrics import adjusted_rand_score

from app.nlp.classify import attribute_features, classify_text, propagate_labels, sentiment


def test_heuristic_classifier_examples():
    assert classify_text("The report page takes forever to load and then crashes")[0] == "Performance Issue"
    assert classify_text("Too many clicks, the workflow is clunky and confusing")[0] == "UX Friction"
    assert classify_text("Nobody uses this, please let admins disable it")[0] == "Feature Bloat Indicator"
    assert classify_text("We rely on it every day, huge time saver")[0] == "Core Utility"
    assert sentiment("love it, essential", "Core Utility") > 0 > sentiment("slow and broken", "Performance Issue")


def test_attribution():
    feats = [("F1", "Deal Pipeline"), ("F2", "Email Sync")]
    assert attribute_features(["the deal pipeline is slow", "email sync failed", "app is slow"], feats) == ["F1", "F2", ""]


def test_label_propagation():
    v = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.9]], dtype=float)
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    labels, _ = propagate_labels(v, {0: "A", 2: "B"}, k=1)
    assert labels == ["A", "A", "B", "B"]


def test_mining_quality(mined, synth):
    t = mined.tickets
    truth_cat = t["ticket_id"].map(synth.truth["category"])
    assert (t["category"] == truth_cat).mean() > 0.9
    ari = adjusted_rand_score(t["ticket_id"].map(synth.truth["theme"]), t["cluster_id"])
    assert ari > 0.6, ari
    inferred = t[t["attribution"] == "inferred"]
    assert (inferred["feature_id"] == inferred["ticket_id"].map(synth.truth["feature"])).mean() > 0.85
    assert 6 <= mined.meta["n_clusters"] <= 16
    assert all(c["name"] for c in mined.clusters)
    assert set(mined.per_feature.columns) >= {"tickets", "friction_per_month", "bloat_share"}

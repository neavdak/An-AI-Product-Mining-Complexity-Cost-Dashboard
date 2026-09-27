import pandas as pd
import pytest

from app.engine import ModelParams, compute, fmt_inr, normalise, portfolio_summary


def test_normalise_percentile_and_minmax():
    s = pd.Series([1, 10, 100, 1000])
    assert normalise(s).tolist() == pytest.approx([0, 100 / 3, 200 / 3, 100])
    mm = normalise(s, "minmax")
    assert mm.iloc[0] == 0 and mm.iloc[-1] == 100
    assert normalise(pd.Series([5, 5])).tolist() == [50, 50]


def test_fmt_inr():
    assert fmt_inr(12_300_000) == "₹1.23Cr"
    assert fmt_inr(345_000) == "₹3.5L"
    assert fmt_inr(-4_500) == "-₹4.5K"


def test_traps_recover_archetypes(dataset, mined, synth):
    df = compute(dataset, mined.per_feature, ModelParams())
    arche = df["feature_id"].map(synth.truth["archetype"])
    traps = df[arche == "trap"]
    assert traps["is_complexity_trap"].mean() >= 0.8
    # cash cows should never be flagged as traps and mostly be retained
    cows = df[arche == "cash_cow"]
    assert not cows["is_complexity_trap"].any()
    assert (cows["action"].isin(["Retain", "Invest"])).all()
    stars = df[arche == "star"]
    assert (stars["action"] == "Invest").mean() >= 0.6
    assert (df.loc[arche == "question_mark", "plc_stage"].isin(["Introduction", "Growth"])).all()


def test_enterprise_lock_in_prevents_sunset(dataset, mined):
    df = compute(dataset, mined.per_feature, ModelParams()).set_index("feature_name")
    assert df.loc["Legacy SOAP API", "is_complexity_trap"]
    assert df.loc["Legacy SOAP API", "action"] == "Refactor"


def test_thresholds_and_weights_move_results(dataset, mined):
    base = compute(dataset, mined.per_feature, ModelParams())
    strict = compute(dataset, mined.per_feature, ModelParams(roi_threshold=25))
    assert strict["is_complexity_trap"].sum() < base["is_complexity_trap"].sum()
    only_hours = compute(dataset, mined.per_feature, ModelParams(w_maintenance=1, w_bugs=0, w_friction=0))
    assert (only_hours["complexity_index"] == only_hours["c_maintenance"]).all()


def test_summary_consistency(dataset, mined):
    p = ModelParams()
    df = compute(dataset, mined.per_feature, p)
    s = portfolio_summary(df, p)
    assert s["n_features"] == len(df)
    assert sum(s["quadrants"].values()) == len(df) == sum(s["actions"].values())
    assert s["total_eng_cost_monthly"] == pytest.approx(df["maintenance_hours"].sum() * p.hourly_rate_inr, rel=1e-3)
    assert 0 < s["trap_hours_share"] < 1

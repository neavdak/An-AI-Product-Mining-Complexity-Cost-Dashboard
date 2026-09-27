"""Modules 3 & 4 - Complexity Cost vs. Return engine + MBA framework mapping.

For every feature we compute:

    Complexity Index = Σ w · Normalised(maintenance hours, bug-ticket frequency, feedback friction)
    ROI Index        = Σ w · Normalised(adoption rate × attributed revenue, enterprise dependency)

and then map the portfolio onto:
  * a Complexity-vs-ROI matrix  -> "Complexity Trap" flag (high cost / low return)
  * a modified BCG matrix       -> Star / Cash Cow / Question Mark / Dog
  * the Product Lifecycle       -> Introduction / Growth / Maturity / Decline
  * an executive action         -> Invest / Retain / Refactor / Sunset / Monitor
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .ingest import Dataset

QUADRANTS = ["Complexity Trap", "Strategic Heavyweight", "Efficient Core", "Low-Cost Long Tail"]
BCG = ["Star", "Cash Cow", "Question Mark", "Dog"]
PLC = ["Introduction", "Growth", "Maturity", "Decline"]
ACTIONS = ["Invest", "Retain", "Refactor", "Monitor", "Sunset"]
HOURS_PER_FTE_MONTH = 140  # productive engineering hours per FTE per month


class ModelParams(BaseModel):
    """Tunable assumptions - exposed as sliders in the dashboard."""

    w_maintenance: float = Field(0.5, ge=0, le=1, description="Complexity weight: maintenance hours")
    w_bugs: float = Field(0.3, ge=0, le=1, description="Complexity weight: bug-ticket frequency")
    w_friction: float = Field(0.2, ge=0, le=1, description="Complexity weight: UX/performance feedback volume")
    w_revenue: float = Field(0.75, ge=0, le=1, description="ROI weight: adoption × attributed revenue")
    w_enterprise: float = Field(0.25, ge=0, le=1, description="ROI weight: enterprise client dependency")
    complexity_threshold: float = Field(50, ge=0, le=100)
    roi_threshold: float = Field(50, ge=0, le=100)
    growth_threshold: float = Field(0.10, ge=-1, le=5, description="BCG high-growth cut-off (usage growth over lookback)")
    share_threshold: float = Field(1.0, gt=0, le=10, description="BCG relative-share cut-off (adoption vs portfolio median)")
    hourly_rate_inr: float = Field(2500, ge=0, description="Fully-loaded engineering cost per hour (INR)")
    lookback_months: int = Field(6, ge=1, le=24)
    normalization: Literal["percentile", "minmax"] = "percentile"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def fmt_inr(x: float) -> str:
    """Indian notation: ₹1.2Cr, ₹34.5L, ₹12.3K."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f}Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.1f}L"
    if a >= 1e3:
        return f"{sign}₹{a / 1e3:.1f}K"
    return f"{sign}₹{a:.0f}"


def normalise(s: pd.Series, method: str = "percentile") -> pd.Series:
    s = s.astype(float).fillna(0.0)
    if len(s) == 0:
        return s
    if s.nunique() <= 1:
        return pd.Series(50.0, index=s.index)
    if method == "percentile":
        # mid-rank percentile scaled to [0, 100]
        r = s.rank(method="average")
        return (r - 1) / (len(s) - 1) * 100
    v = np.log1p(s.clip(lower=0))
    return (v - v.min()) / (v.max() - v.min()) * 100


def _weighted(parts: list[tuple[float, pd.Series]]) -> pd.Series:
    total = sum(w for w, _ in parts)
    if total <= 0:
        return pd.Series(50.0, index=parts[0][1].index)
    return sum(w * s for w, s in parts) / total


def _window_mean(s: pd.Series, n: int) -> float:
    return float(s.tail(n).mean()) if len(s) else 0.0


# ---------------------------------------------------------------------------
# core computation
# ---------------------------------------------------------------------------
def compute(ds: Dataset, feedback_per_feature: pd.DataFrame | None, params: ModelParams) -> pd.DataFrame:
    f = ds.features.set_index("feature_id")
    usage, eng = ds.usage, ds.engineering
    L = params.lookback_months
    as_of = usage["month"].max() if len(usage) else pd.Timestamp.today().normalize()

    rows = []
    for fid, feat in f.iterrows():
        us = usage.loc[usage["feature_id"] == fid].set_index("month")["active_users"].sort_index()
        es = eng.loc[eng["feature_id"] == fid].set_index("month").sort_index()
        active_now = float(us.iloc[-1]) if len(us) else 0.0
        peak = float(us.max()) if len(us) else 0.0
        recent = _window_mean(us, 3)
        nz = us[us > 0]
        if len(us) >= L + 3:
            base = float(us.iloc[-(L + 3):-L].mean())
        elif len(nz):
            base = float(nz.iloc[: min(3, len(nz))].mean()) if len(nz) > 3 else float(nz.iloc[0])
        else:
            base = 0.0
        growth = (recent / base - 1) if base > 0 else 0.0
        growth = float(np.clip(growth, -1, 3))

        hours = _window_mean(es["maintenance_hours"], L) if len(es) else 0.0
        bugs = _window_mean(es["bug_tickets"], L) if len(es) else 0.0
        commits = _window_mean(es["commits"], L) if "commits" in es and len(es) else 0.0
        incidents = _window_mean(es["incidents"], L) if "incidents" in es and len(es) else 0.0
        hours_prev = float(es["maintenance_hours"].iloc[-6:-3].mean()) if len(es) >= 6 else hours
        hours_trend = float(_window_mean(es["maintenance_hours"], 3) / hours_prev - 1) if hours_prev else 0.0

        release = pd.to_datetime(feat.get("release_date"), errors="coerce")
        age = max(0.0, (as_of - release).days / 30.44) if pd.notna(release) else float("nan")
        eligible = float(feat["eligible_users"]) or 1.0
        revenue = float(feat["monthly_revenue_inr"])
        eng_cost = hours * params.hourly_rate_inr
        net = revenue - eng_cost
        rows.append({
            "feature_id": fid,
            "feature_name": feat["feature_name"],
            "module": feat["module"],
            "tier": feat["tier"],
            "description": feat.get("description", ""),
            "release_date": release.date().isoformat() if pd.notna(release) else None,
            "age_months": round(age, 1) if age == age else None,
            "development_cost_inr": float(feat["development_cost_inr"]),
            "monthly_revenue_inr": revenue,
            "enterprise_clients": float(feat["enterprise_clients"]),
            "eligible_users": eligible,
            "active_users": active_now,
            "peak_users": peak,
            "peak_ratio": round(active_now / peak, 3) if peak else 0.0,
            "adoption_rate": round(active_now / eligible, 4),
            "usage_growth": round(growth, 4),
            "maintenance_hours": round(hours, 1),
            "maintenance_hours_trend": round(hours_trend, 3),
            "bug_tickets": round(bugs, 2),
            "commits": round(commits, 1),
            "incidents": round(incidents, 2),
            "eng_cost_monthly": round(eng_cost, 0),
            "net_contribution_monthly": round(net, 0),
            "cost_to_revenue": round(eng_cost / revenue, 2) if revenue > 0 else None,
            "dev_payback_months": round(float(feat["development_cost_inr"]) / net, 1) if net > 0 else None,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # ---- feedback signals
    fb_cols = ["tickets", "tickets_per_month", "avg_sentiment", "friction_per_month", "bloat_share", "top_theme",
               "Core Utility", "UX Friction", "Performance Issue", "Feature Bloat Indicator"]
    if feedback_per_feature is not None and len(feedback_per_feature):
        df = df.merge(feedback_per_feature[["feature_id"] + fb_cols], on="feature_id", how="left")
    for c in fb_cols:
        if c not in df:
            df[c] = np.nan
    for c in fb_cols:
        if c != "top_theme":
            df[c] = df[c].fillna(0.0)
    df["top_theme"] = df["top_theme"].fillna("–")

    # ---- indices
    m = params.normalization
    df["adoption_revenue"] = df["adoption_rate"] * df["monthly_revenue_inr"]
    comp_parts = {
        "maintenance": normalise(df["maintenance_hours"], m),
        "bugs": normalise(df["bug_tickets"], m),
        "friction": normalise(df["friction_per_month"], m),
    }
    roi_parts = {
        "revenue": normalise(df["adoption_revenue"], m),
        "enterprise": normalise(df["enterprise_clients"], m),
    }
    df["complexity_index"] = _weighted([(params.w_maintenance, comp_parts["maintenance"]),
                                        (params.w_bugs, comp_parts["bugs"]),
                                        (params.w_friction, comp_parts["friction"])]).round(1)
    df["roi_index"] = _weighted([(params.w_revenue, roi_parts["revenue"]),
                                 (params.w_enterprise, roi_parts["enterprise"])]).round(1)
    for k, v in comp_parts.items():
        df[f"c_{k}"] = v.round(1)
    for k, v in roi_parts.items():
        df[f"r_{k}"] = v.round(1)

    # ---- complexity-ROI quadrant
    hi_c = df["complexity_index"] >= params.complexity_threshold
    hi_r = df["roi_index"] >= params.roi_threshold
    df["quadrant"] = np.select(
        [hi_c & ~hi_r, hi_c & hi_r, ~hi_c & hi_r], QUADRANTS[:3], default=QUADRANTS[3])
    df["is_complexity_trap"] = hi_c & ~hi_r
    df["trap_score"] = ((df["complexity_index"] - df["roi_index"] + 100) / 2).round(1)

    # ---- BCG (relative adoption share vs portfolio median, usage growth)
    med = float(df.loc[df["adoption_rate"] > 0, "adoption_rate"].median() or 1e-9)
    df["relative_share"] = (df["adoption_rate"] / med).round(3)
    hi_s = df["relative_share"] >= params.share_threshold
    hi_g = df["usage_growth"] >= params.growth_threshold
    df["bcg"] = np.select([hi_s & hi_g, hi_s & ~hi_g, ~hi_s & hi_g], BCG[:3], default=BCG[3])

    # ---- Product lifecycle
    def plc(r) -> str:
        age = r.age_months if r.age_months is not None and r.age_months == r.age_months else 999.0
        if age < 6 or (age < 12 and r.usage_growth > params.growth_threshold and r.adoption_rate < 0.15):
            return "Introduction"
        if r.usage_growth >= params.growth_threshold:
            return "Growth"
        if r.usage_growth <= -0.08 or (r.peak_ratio < 0.8 and r.usage_growth < 0):
            return "Decline"
        return "Maturity"

    df["plc_stage"] = df.apply(plc, axis=1)

    # ---- Recommendation
    # Enterprise lock-in: a meaningful share of the enterprise base depends on the feature.
    ent_hi = df["enterprise_clients"] >= max(10.0, 0.25 * float(df["enterprise_clients"].max()))
    df["enterprise_lock_in"] = ent_hi
    hours_pct = normalise(df["maintenance_hours"], "percentile")
    actions, rationales, confidences = [], [], []
    for i, r in df.iterrows():
        a, why = _recommend(r, bool(ent_hi.iloc[i]), params)
        margin = min(abs(r.complexity_index - params.complexity_threshold), abs(r.roi_index - params.roi_threshold))
        conf = "High" if margin >= 15 else "Medium" if margin >= 6 else "Low"
        facts = (f"{r.maintenance_hours:.0f} eng hrs/mo ({fmt_inr(r.eng_cost_monthly)}, costlier than "
                 f"{hours_pct.iloc[i]:.0f}% of the portfolio) vs {fmt_inr(r.monthly_revenue_inr)}/mo attributed revenue; "
                 f"adoption {r.adoption_rate:.1%}, usage {r.usage_growth:+.0%} over {params.lookback_months} mo")
        if r.tickets:
            facts += f"; {r.bloat_share:.0%} of feedback signals bloat, sentiment {r.avg_sentiment:+.2f}"
        actions.append(a)
        rationales.append(f"{why} — {facts}.")
        confidences.append(conf)
    df["action"] = actions
    df["rationale"] = rationales
    df["confidence"] = confidences
    return df


def _recommend(r: pd.Series, ent_lock: bool, p: ModelParams) -> tuple[str, str]:
    growing = r.plc_stage in ("Introduction", "Growth")
    if r.quadrant == "Complexity Trap":
        if growing:
            return "Refactor", "Complexity trap in an early lifecycle stage: re-scope and harden before scaling further"
        if ent_lock:
            return "Refactor", (f"Complexity trap with enterprise lock-in ({r.enterprise_clients:.0f} enterprise clients): "
                                "migrate dependents to a leaner alternative, then consolidate")
        return "Sunset", "Complexity trap: engineering cost far exceeds return with no growth signal - deprecate and reinvest"
    if r.quadrant == "Strategic Heavyweight":
        if r.bcg == "Star" or r.plc_stage == "Growth":
            return "Invest", "Star heavyweight: high return and growing - invest to scale while hardening the codebase"
        return "Refactor", "High-return but engineering-heavy: pay down tech debt to protect margin on a core revenue line"
    if r.quadrant == "Efficient Core":
        if r.usage_growth >= p.growth_threshold:
            return "Invest", "Efficient star: strong return, low overhead and growing - double down"
        if r.plc_stage == "Decline":
            return "Retain", "Cash cow in decline: harvest profitably, freeze new investment and watch churn"
        return "Retain", "Cash cow: high return at low maintenance cost - harvest and keep stable"
    if r.plc_stage == "Decline" and r.bloat_share >= 0.25:
        return "Sunset", "Declining long-tail feature customers call bloat - trim surface area even though it is cheap"
    if growing:
        return "Monitor", "Question mark: cheap to run and growing - nurture with limited bets until ROI signal is clear"
    return "Monitor", "Low-cost long tail: acceptable overhead - keep on maintenance mode and review quarterly"


# ---------------------------------------------------------------------------
# portfolio roll-ups
# ---------------------------------------------------------------------------
def portfolio_summary(df: pd.DataFrame, params: ModelParams) -> dict:
    if df.empty:
        return {}
    traps = df[df["is_complexity_trap"]]
    sunset = df[df["action"] == "Sunset"]
    total_hours = float(df["maintenance_hours"].sum())
    total_rev = float(df["monthly_revenue_inr"].sum())
    total_cost = float(df["eng_cost_monthly"].sum())

    # Pareto: share of revenue from top-20% features; share of eng hours on bottom-50% ROI features
    n20 = max(1, int(round(len(df) * 0.2)))
    top_rev_share = float(df.nlargest(n20, "monthly_revenue_inr")["monthly_revenue_inr"].sum() / total_rev) if total_rev else 0
    low_roi = df[df["roi_index"] < df["roi_index"].median()]
    low_roi_hours_share = float(low_roi["maintenance_hours"].sum() / total_hours) if total_hours else 0

    module = (df.groupby("module").agg(
        features=("feature_id", "count"), revenue=("monthly_revenue_inr", "sum"), eng_cost=("eng_cost_monthly", "sum"),
        hours=("maintenance_hours", "sum"), traps=("is_complexity_trap", "sum"),
        complexity=("complexity_index", "mean"), roi=("roi_index", "mean"))
        .reset_index().sort_values("revenue", ascending=False))
    module["net"] = module["revenue"] - module["eng_cost"]

    def counts(col, order):
        vc = df[col].value_counts()
        return {k: int(vc.get(k, 0)) for k in order}

    return {
        "n_features": int(len(df)),
        "total_revenue_monthly": total_rev,
        "total_eng_hours_monthly": total_hours,
        "total_eng_cost_monthly": total_cost,
        "net_contribution_monthly": total_rev - total_cost,
        "eng_cost_to_revenue": round(total_cost / total_rev, 3) if total_rev else None,
        "engineering_fte": round(total_hours / HOURS_PER_FTE_MONTH, 1),
        "n_traps": int(len(traps)),
        "trap_eng_hours_monthly": float(traps["maintenance_hours"].sum()),
        "trap_eng_cost_monthly": float(traps["eng_cost_monthly"].sum()),
        "complexity_tax_annual": float(traps["eng_cost_monthly"].sum() * 12),
        "trap_hours_share": round(float(traps["maintenance_hours"].sum() / total_hours), 4) if total_hours else 0,
        "trap_revenue_share": round(float(traps["monthly_revenue_inr"].sum() / total_rev), 4) if total_rev else 0,
        "trap_fte": round(float(traps["maintenance_hours"].sum()) / HOURS_PER_FTE_MONTH, 1),
        "sunset": {
            "count": int(len(sunset)),
            "eng_savings_annual": float(sunset["eng_cost_monthly"].sum() * 12),
            "revenue_at_risk_annual": float(sunset["monthly_revenue_inr"].sum() * 12),
            "fte_freed": round(float(sunset["maintenance_hours"].sum()) / HOURS_PER_FTE_MONTH, 1),
            "net_annual_impact": float((sunset["eng_cost_monthly"] - sunset["monthly_revenue_inr"]).sum() * 12),
        },
        "pareto": {"top20_revenue_share": round(top_rev_share, 3), "low_roi_hours_share": round(low_roi_hours_share, 3)},
        "quadrants": counts("quadrant", QUADRANTS),
        "bcg": counts("bcg", BCG),
        "plc": counts("plc_stage", PLC),
        "actions": counts("action", ACTIONS),
        "modules": module.round(1).to_dict(orient="records"),
        "params": params.model_dump(),
    }

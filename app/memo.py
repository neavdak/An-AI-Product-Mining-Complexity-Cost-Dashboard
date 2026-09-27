"""Executive memo generation (LLM when available, deterministic template otherwise)."""

from __future__ import annotations

import pandas as pd

from .engine import fmt_inr
from .nlp.llm import LLMClient


def memo_context(df: pd.DataFrame, summary: dict, clusters: list[dict]) -> dict:
    cols = ["feature_name", "module", "complexity_index", "roi_index", "quadrant", "bcg", "plc_stage", "action",
            "maintenance_hours", "eng_cost_monthly", "monthly_revenue_inr", "adoption_rate", "usage_growth", "bloat_share"]
    traps = df[df["is_complexity_trap"]].sort_values("trap_score", ascending=False)[cols].head(8)
    stars = df[df["action"] == "Invest"].sort_values("roi_index", ascending=False)[cols].head(5)
    s = {k: v for k, v in summary.items() if k not in ("modules", "params")}
    return {
        "portfolio": s,
        "top_complexity_traps": traps.round(3).to_dict(orient="records"),
        "invest_candidates": stars.round(3).to_dict(orient="records"),
        "top_feedback_themes": [{k: c[k] for k in ("name", "category", "size", "avg_sentiment")} for c in clusters[:6]],
    }


def template_memo(df: pd.DataFrame, summary: dict, clusters: list[dict]) -> str:
    s = summary
    sun = s["sunset"]
    traps = df[df["is_complexity_trap"]].sort_values("trap_score", ascending=False)
    invest = df[df["action"] == "Invest"].sort_values("roi_index", ascending=False)
    refactor = df[df["action"] == "Refactor"].sort_values("complexity_index", ascending=False)
    top_trap_names = ", ".join(f"**{n}**" for n in traps["feature_name"].head(4))
    neg_themes = [c for c in clusters if c["category"] != "Core Utility"][:3]

    lines = [
        "## Headline",
        (f"{s['n_traps']} of {s['n_features']} features are complexity traps: they absorb "
         f"**{s['trap_hours_share']:.0%} of engineering capacity** ({s['trap_fte']} FTE, "
         f"{fmt_inr(s['complexity_tax_annual'])}/yr) while generating only **{s['trap_revenue_share']:.1%} of revenue**."),
        "",
        "## Key findings",
        (f"- **Pareto concentration:** the top 20% of features drive {s['pareto']['top20_revenue_share']:.0%} of attributed "
         f"revenue, while below-median-ROI features consume {s['pareto']['low_roi_hours_share']:.0%} of maintenance hours."),
        (f"- **Portfolio economics:** {fmt_inr(s['total_revenue_monthly'])}/mo attributed revenue vs "
         f"{fmt_inr(s['total_eng_cost_monthly'])}/mo maintenance cost ({s['engineering_fte']} FTE); "
         f"engineering cost-to-revenue ratio {s['eng_cost_to_revenue']:.0%}."),
        f"- **Worst complexity traps:** {top_trap_names or 'none detected'}.",
        (f"- **BCG mix:** {s['bcg']['Star']} Stars, {s['bcg']['Cash Cow']} Cash Cows, "
         f"{s['bcg']['Question Mark']} Question Marks, {s['bcg']['Dog']} Dogs; lifecycle: "
         f"{s['plc']['Growth']} in Growth, {s['plc']['Decline']} in Decline."),
    ]
    if neg_themes:
        lines.append("- **Voice of customer:** dominant pain themes are "
                     + ", ".join(f"*{c['name']}* ({c['size']} tickets)" for c in neg_themes) + ".")
    lines += ["", "## Recommended actions"]
    if sun["count"]:
        sunset_names = ", ".join(df[df["action"] == "Sunset"].sort_values("trap_score", ascending=False)["feature_name"].head(5))
        lines.append(f"- **Sunset {sun['count']} features** ({sunset_names}): frees ~{sun['fte_freed']} FTE and "
                     f"{fmt_inr(sun['eng_savings_annual'])}/yr against {fmt_inr(sun['revenue_at_risk_annual'])}/yr "
                     f"revenue at risk - net {fmt_inr(sun['net_annual_impact'])}/yr.")
    if len(refactor):
        lines.append("- **Refactor** high-cost lines that still matter commercially: "
                     + ", ".join(refactor["feature_name"].head(4)) + ".")
    if len(invest):
        lines.append("- **Reinvest freed capacity** in Stars and efficient growth bets: "
                     + ", ".join(invest["feature_name"].head(4)) + ".")
    lines.append("- **Governance:** add a complexity-cost gate to quarterly roadmap reviews so new features carry "
                 "an explicit maintenance budget and sunset criteria.")
    lines += [
        "",
        "## Risks & mitigations",
        "- *Enterprise contracts* may reference deprecated features - run migration paths and 2-quarter notice periods.",
        "- *Attribution error* in revenue mapping - validate top candidates with Finance before committing.",
        "- *Hidden dependencies* - confirm with engineering that sunset candidates are not shared infrastructure.",
    ]
    return "\n".join(lines)


def generate_memo(llm: LLMClient, df: pd.DataFrame, summary: dict, clusters: list[dict]) -> tuple[str, str]:
    """Return (markdown, source)."""
    if llm.enabled:
        text = llm.write_memo(memo_context(df, summary, clusters))
        if text and len(text) > 80:
            return text.strip(), f"{llm.provider}:{llm.model}"
    return template_memo(df, summary, clusters), "template"

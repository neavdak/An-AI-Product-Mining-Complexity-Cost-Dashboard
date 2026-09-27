"""Command-line interface.

    python -m app.cli generate --out data/sample --seed 42
    python -m app.cli analyze --data data/sample --out reports/
    python -m app.cli serve --port 8000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_generate(a):
    from .synthetic import generate

    ds = generate(seed=a.seed, feedback_scale=a.feedback_scale)
    out = ds.save(a.out)
    print(f"Wrote {len(ds.features)} features, {len(ds.usage)} usage rows, {len(ds.engineering)} engineering rows, "
          f"{len(ds.feedback)} feedback tickets -> {out}")


def cmd_analyze(a):
    from .config import get_settings
    from .engine import ModelParams, compute, fmt_inr, portfolio_summary
    from .ingest import load_folder
    from .memo import generate_memo
    from .mining import mine_feedback
    from .nlp.llm import LLMClient

    settings = get_settings()
    ds = load_folder(a.data)
    for w in ds.warnings:
        print("warning:", w)
    llm = LLMClient(settings)
    print(f"Intelligence layer: {llm.provider} ({llm.model})")
    fb = mine_feedback(ds, llm, settings)
    print(f"Mined {fb.meta['n_tickets']} tickets into {fb.meta.get('n_clusters', 0)} themes "
          f"[{fb.meta.get('embedding_backend')}] in {fb.meta['elapsed_s']}s")
    params = ModelParams(**json.loads(a.params)) if a.params else ModelParams()
    df = compute(ds, fb.per_feature, params)
    summary = portfolio_summary(df, params)
    memo, source = generate_memo(llm, df, summary, fb.clusters)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "feature_portfolio_analysis.csv", index=False)
    fb.tickets.drop(columns=["x", "y"]).to_csv(out / "feedback_mined.csv", index=False)
    (out / "feedback_themes.json").write_text(json.dumps(fb.clusters, indent=2, default=str))
    (out / "portfolio_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out / "executive_memo.md").write_text(memo)

    print(f"\n{summary['n_traps']} complexity traps · complexity tax {fmt_inr(summary['complexity_tax_annual'])}/yr · "
          f"{summary['trap_hours_share']:.0%} of eng hours for {summary['trap_revenue_share']:.1%} of revenue")
    top = df[df["is_complexity_trap"]].sort_values("trap_score", ascending=False).head(8)
    for r in top.itertuples():
        print(f"  {r.action:<8} {r.feature_name:<32} C={r.complexity_index:5.1f} ROI={r.roi_index:5.1f} "
              f"cost {fmt_inr(r.eng_cost_monthly)}/mo vs rev {fmt_inr(r.monthly_revenue_inr)}/mo")
    print(f"\nReports written to {out}/ (memo source: {source})")


def cmd_serve(a):
    import uvicorn

    uvicorn.run("app.main:app", host=a.host, port=a.port, reload=a.reload)


def main():
    p = argparse.ArgumentParser(prog="complexity-cost", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="Generate a synthetic enterprise dataset (CSV)")
    g.add_argument("--out", default="data/sample")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--feedback-scale", type=float, default=1.0)
    g.set_defaults(fn=cmd_generate)
    an = sub.add_parser("analyze", help="Run the full pipeline on a folder of CSVs and write reports")
    an.add_argument("--data", default="data/sample")
    an.add_argument("--out", default="reports")
    an.add_argument("--params", help='JSON overrides, e.g. \'{"roi_threshold": 40}\'')
    an.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("serve", help="Run the API + dashboard")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

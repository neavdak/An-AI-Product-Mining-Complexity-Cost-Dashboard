"""FastAPI application: REST API + static dashboard."""

from __future__ import annotations

import io
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import SAMPLE_DATA_DIR, WEB_DIR
from .engine import ModelParams
from .ingest import FILENAMES, DataValidationError, from_synthetic, load_uploads
from .pipeline import get_pipeline
from .synthetic import generate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

Params = Annotated[ModelParams, Query()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    pipe = get_pipeline()
    try:
        pipe.run(pipe.default_dataset(), background=True)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not load default dataset: %s", exc)
    yield


app = FastAPI(
    title="AI Product Mining & Complexity Cost API",
    version=__version__,
    description="Mines customer feedback with embeddings + LLMs and maps product features against "
                "maintenance overhead vs. revenue to flag complexity traps.",
    lifespan=lifespan,
)


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _ready():
    pipe = get_pipeline()
    if pipe.state.dataset is None:
        st = pipe.state
        raise HTTPException(status_code=503, detail={"status": st.status, "stage": st.stage, "error": st.error})
    return pipe


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/status")
def status():
    return get_pipeline().status()


@app.get("/api/params/defaults")
def param_defaults():
    return {"defaults": ModelParams().model_dump(), "schema": ModelParams.model_json_schema()}


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
@app.get("/api/analysis")
def analysis(params: Params):
    pipe = _ready()
    df, summary = pipe.analysis(params)
    return {"summary": summary, "features": _records(df), "version": pipe.state.version}


@app.get("/api/features/{feature_id}")
def feature_detail(feature_id: str, params: Params):
    pipe = _ready()
    df, _ = pipe.analysis(params)
    row = df[df["feature_id"] == feature_id]
    if row.empty:
        raise HTTPException(404, f"Unknown feature {feature_id}")
    ds, fb = pipe.state.dataset, pipe.state.feedback
    usage = ds.usage[ds.usage["feature_id"] == feature_id]
    eng = ds.engineering[ds.engineering["feature_id"] == feature_id]
    tickets = fb.tickets[fb.tickets["feature_id"] == feature_id]
    themes = (tickets.groupby("cluster_name").agg(count=("ticket_id", "count"), sentiment=("sentiment", "mean"))
              .reset_index().sort_values("count", ascending=False).round(3))
    quotes = (pd.concat([tickets.nsmallest(3, "sentiment"), tickets.nlargest(2, "sentiment")]).drop_duplicates("ticket_id")
              if len(tickets) else tickets)
    return {
        "feature": _records(row)[0],
        "usage": [{"month": m.strftime("%Y-%m"), "active_users": int(v)} for m, v in zip(usage["month"], usage["active_users"])],
        "engineering": [{"month": r.month.strftime("%Y-%m"), "maintenance_hours": r.maintenance_hours,
                         "bug_tickets": int(r.bug_tickets)} for r in eng.itertuples()],
        "themes": _records(themes),
        "quotes": _records(quotes[["ticket_id", "text", "category", "sentiment", "source", "created_at"]]),
    }


@app.get("/api/series")
def series():
    """Monthly usage + engineering series for every feature (for lifecycle heatmaps)."""
    ds = _ready().state.dataset
    months = sorted(ds.usage["month"].dt.strftime("%Y-%m").unique().tolist())
    usage: dict[str, dict[str, int]] = {}
    for r in ds.usage.itertuples():
        usage.setdefault(r.feature_id, {})[r.month.strftime("%Y-%m")] = int(r.active_users)
    hours: dict[str, dict[str, float]] = {}
    for r in ds.engineering.itertuples():
        hours.setdefault(r.feature_id, {})[r.month.strftime("%Y-%m")] = float(r.maintenance_hours)
    return {"months": months, "usage": usage, "maintenance_hours": hours}


@app.get("/api/memo")
def memo(params: Params):
    return _ready().memo(params)


# ---------------------------------------------------------------------------
# feedback intelligence
# ---------------------------------------------------------------------------
@app.get("/api/feedback/clusters")
def clusters():
    pipe = _ready()
    return {"clusters": pipe.state.feedback.clusters, "meta": pipe.state.feedback.meta}


@app.get("/api/feedback/map")
def feedback_map():
    t = _ready().state.feedback.tickets
    return {"x": t["x"].tolist(), "y": t["y"].tolist(), "cluster": t["cluster_name"].fillna("").tolist(),
            "category": t["category"].tolist(), "feature": t["feature_name"].tolist(),
            "text": t["text"].str.slice(0, 140).tolist(), "sentiment": t["sentiment"].tolist()}


@app.get("/api/feedback/tickets")
def tickets(
    feature_id: str | None = None,
    cluster_id: int | None = None,
    category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    sort: str = "sentiment",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    t = _ready().state.feedback.tickets
    if feature_id:
        t = t[t["feature_id"] == feature_id]
    if cluster_id is not None:
        t = t[t["cluster_id"] == cluster_id]
    if category:
        t = t[t["category"] == category]
    if source:
        t = t[t["source"] == source]
    if q:
        t = t[t["text"].str.contains(q, case=False, regex=False)]
    if sort in ("sentiment", "created_at", "category_confidence"):
        t = t.sort_values(sort, ascending=sort == "sentiment")
    page = t.iloc[offset: offset + limit].drop(columns=["x", "y"])
    return {"total": int(len(t)), "items": _records(page)}


@app.get("/api/feedback/heatmap")
def heatmap():
    t = _ready().state.feedback.tickets
    t = t[t["feature_id"] != ""]
    if t.empty:
        return {"features": [], "categories": [], "z": []}
    ct = pd.crosstab(t["feature_name"], t["category"])
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index]
    return {"features": ct.index.tolist(), "categories": ct.columns.tolist(), "z": ct.values.tolist()}


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------
class SyntheticRequest(BaseModel):
    seed: int = Field(42, ge=0, le=10_000_000)
    feedback_scale: float = Field(1.0, ge=0.2, le=5.0)


def _start(ds) -> JSONResponse:
    try:
        get_pipeline().run(ds, background=True)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse({"accepted": True, "dataset": ds.summary()}, status_code=202)


@app.post("/api/datasets/synthetic")
def regenerate(req: SyntheticRequest):
    ds = from_synthetic(generate(seed=req.seed, feedback_scale=req.feedback_scale),
                        name=f"Synthetic SaaS (seed {req.seed})")
    return _start(ds)


@app.post("/api/datasets/upload")
async def upload(
    features: UploadFile = File(...),
    usage: UploadFile | None = File(None),
    engineering: UploadFile | None = File(None),
    feedback: UploadFile | None = File(None),
):
    files = {}
    for key, up in (("features", features), ("usage", usage), ("engineering", engineering), ("feedback", feedback)):
        if up is not None and up.filename:
            files[key] = await up.read()
    try:
        ds = load_uploads(files, name=f"Uploaded: {features.filename}")
    except DataValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _start(ds)


@app.get("/api/datasets/template/{table}")
def template(table: str):
    if table not in FILENAMES:
        raise HTTPException(404, f"Unknown table; choose one of {list(FILENAMES)}")
    path = SAMPLE_DATA_DIR / FILENAMES[table]
    if not path.exists():
        generate().save(SAMPLE_DATA_DIR)
    return FileResponse(path, media_type="text/csv", filename=FILENAMES[table])


# ---------------------------------------------------------------------------
# exports
# ---------------------------------------------------------------------------
def _csv_response(df: pd.DataFrame, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/features.csv")
def export_features(params: Params):
    df, _ = _ready().analysis(params)
    return _csv_response(df, "feature_portfolio_analysis.csv")


@app.get("/api/export/tickets.csv")
def export_tickets():
    t = _ready().state.feedback.tickets.drop(columns=["x", "y"])
    return _csv_response(t, "feedback_mined.csv")


@app.get("/api/export/memo.md")
def export_memo(params: Params):
    m = _ready().memo(params)
    return PlainTextResponse(m["markdown"], headers={"Content-Disposition": 'attachment; filename="executive_memo.md"'})


# ---------------------------------------------------------------------------
# frontend
# ---------------------------------------------------------------------------
@app.get("/vendor/plotly.min.js")
def plotly_js():
    """Serve Plotly from the installed Python package so the UI works fully offline."""
    import plotly

    path = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if not path.exists():
        return Response("console.error('plotly.min.js not found')", media_type="application/javascript")
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "public, max-age=86400"})


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

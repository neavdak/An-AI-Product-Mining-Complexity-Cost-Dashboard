"""Data ingestion, schema normalisation and validation.

Accepts either the "full" four-table layout produced by the synthetic
generator, or a minimal "flat" catalog where usage and engineering overhead
are single columns on the feature table. Common alternative column names
(e.g. ``direct_revenue_attributed``, ``tier_dependency``) are mapped
automatically so real exports need minimal massaging.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

TABLES = ("features", "usage", "engineering", "feedback")
FILENAMES = {
    "features": "features.csv",
    "usage": "usage_monthly.csv",
    "engineering": "engineering_logs.csv",
    "feedback": "feedback.csv",
}

ALIASES: dict[str, dict[str, str]] = {
    "features": {
        "id": "feature_id", "feature": "feature_name", "name": "feature_name",
        "product_area": "module", "category": "module",
        "direct_revenue_attributed": "monthly_revenue_inr", "direct_revenue_attributed_inr": "monthly_revenue_inr",
        "revenue": "monthly_revenue_inr", "monthly_revenue": "monthly_revenue_inr", "mrr": "monthly_revenue_inr",
        "tier_dependency": "enterprise_clients", "enterprise_accounts": "enterprise_clients",
        "dev_cost": "development_cost_inr", "development_cost": "development_cost_inr",
        "total_users": "eligible_users", "addressable_users": "eligible_users",
        "maintenance_hours": "monthly_maintenance_hours",
        "bug_tickets": "bug_tickets_per_month", "bugs_per_month": "bug_tickets_per_month",
        "mau": "active_users", "monthly_active_users": "active_users",
    },
    "usage": {"date": "month", "period": "month", "mau": "active_users", "users": "active_users"},
    "engineering": {"date": "month", "period": "month", "hours": "maintenance_hours",
                    "time_spent_hours": "maintenance_hours", "bugs": "bug_tickets"},
    "feedback": {"id": "ticket_id", "body": "text", "comment": "text", "feedback": "text",
                 "customer_feedback_text": "text", "description": "text", "date": "created_at"},
}

REQUIRED = {
    "features": ["feature_id", "feature_name"],
    "usage": ["feature_id", "month", "active_users"],
    "engineering": ["feature_id", "month", "maintenance_hours"],
    "feedback": ["text"],
}


class DataValidationError(ValueError):
    pass


@dataclass
class Dataset:
    features: pd.DataFrame
    usage: pd.DataFrame
    engineering: pd.DataFrame
    feedback: pd.DataFrame
    name: str = "dataset"
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        months = sorted(self.usage["month"].dt.strftime("%Y-%m").unique()) if len(self.usage) else []
        return {
            "name": self.name,
            "n_features": int(len(self.features)),
            "n_tickets": int(len(self.feedback)),
            "n_usage_rows": int(len(self.usage)),
            "n_engineering_rows": int(len(self.engineering)),
            "period_start": months[0] if months else None,
            "period_end": months[-1] if months else None,
            "warnings": self.warnings,
        }


def _clean_columns(df: pd.DataFrame, table: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    rename = {c: ALIASES[table][c] for c in df.columns if c in ALIASES[table] and ALIASES[table][c] not in df.columns}
    return df.rename(columns=rename)


def _require(df: pd.DataFrame, table: str) -> None:
    missing = [c for c in REQUIRED[table] if c not in df.columns]
    if missing:
        raise DataValidationError(f"{FILENAMES[table]} is missing required column(s): {', '.join(missing)}")


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    s = df[col]
    if not pd.api.types.is_numeric_dtype(s):
        s = s.astype(str).str.replace(r"[₹,$\s]", "", regex=True)
    return pd.to_numeric(s, errors="coerce").fillna(default)


def normalise(
    features: pd.DataFrame,
    usage: pd.DataFrame | None = None,
    engineering: pd.DataFrame | None = None,
    feedback: pd.DataFrame | None = None,
    name: str = "dataset",
) -> Dataset:
    warnings: list[str] = []

    # ---------------- features ----------------
    f = _clean_columns(features, "features")
    _require(f, "features")
    f["feature_id"] = f["feature_id"].astype(str).str.strip()
    f["feature_name"] = f["feature_name"].astype(str).str.strip()
    if f["feature_id"].duplicated().any():
        dups = f.loc[f["feature_id"].duplicated(), "feature_id"].tolist()
        warnings.append(f"Dropped duplicate feature_id rows: {dups[:5]}")
        f = f.drop_duplicates("feature_id")
    for col, default in [("module", "Unassigned"), ("tier", "All"), ("description", ""), ("owner_team", "")]:
        f[col] = f[col].fillna(default).astype(str) if col in f.columns else default
    for col in ["development_cost_inr", "monthly_revenue_inr", "enterprise_clients"]:
        if col not in f.columns:
            warnings.append(f"features.csv has no '{col}' column - assumed 0.")
        f[col] = _num(f, col)
    today = pd.Timestamp(date.today())
    f["release_date"] = pd.to_datetime(f.get("release_date"), errors="coerce") if "release_date" in f.columns else pd.NaT

    # ---------------- usage ----------------
    if usage is not None and len(usage):
        u = _clean_columns(usage, "usage")
        _require(u, "usage")
        u["feature_id"] = u["feature_id"].astype(str).str.strip()
        u["month"] = pd.to_datetime(u["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
        u["active_users"] = _num(u, "active_users")
        u = u.dropna(subset=["month"]).groupby(["feature_id", "month"], as_index=False)["active_users"].sum()
    elif "active_users" in f.columns:
        warnings.append("No usage_monthly.csv - using single-snapshot active_users (growth & lifecycle limited).")
        u = pd.DataFrame({"feature_id": f["feature_id"], "month": today.to_period("M").to_timestamp(),
                          "active_users": _num(f, "active_users")})
    else:
        raise DataValidationError("Provide usage_monthly.csv or an 'active_users' column in features.csv.")

    # ---------------- engineering ----------------
    if engineering is not None and len(engineering):
        e = _clean_columns(engineering, "engineering")
        _require(e, "engineering")
        e["feature_id"] = e["feature_id"].astype(str).str.strip()
        e["month"] = pd.to_datetime(e["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
        for col in ["maintenance_hours", "bug_tickets", "commits", "incidents"]:
            e[col] = _num(e, col)
        e = e.dropna(subset=["month"]).groupby(["feature_id", "month"], as_index=False)[
            ["maintenance_hours", "bug_tickets", "commits", "incidents"]].sum()
    elif "monthly_maintenance_hours" in f.columns:
        warnings.append("No engineering_logs.csv - using monthly_maintenance_hours from features.csv.")
        e = pd.DataFrame({
            "feature_id": f["feature_id"], "month": u["month"].max(),
            "maintenance_hours": _num(f, "monthly_maintenance_hours"),
            "bug_tickets": _num(f, "bug_tickets_per_month"), "commits": 0.0, "incidents": 0.0,
        })
    else:
        raise DataValidationError("Provide engineering_logs.csv or a 'monthly_maintenance_hours' column in features.csv.")

    # eligible users: explicit, else peak observed usage (adoption then = vs. own peak)
    if "eligible_users" in f.columns:
        f["eligible_users"] = _num(f, "eligible_users")
    else:
        warnings.append("No eligible_users column - adoption computed against the portfolio's largest user base.")
        f["eligible_users"] = float(u["active_users"].max() or 1)
    f["eligible_users"] = f["eligible_users"].where(f["eligible_users"] > 0, float(u["active_users"].max() or 1))

    # infer release date if missing: first month with usage
    if u["month"].nunique() > 1:  # only meaningful with a real time series
        first_seen = u[u["active_users"] > 0].groupby("feature_id")["month"].min()
        f["release_date"] = f["release_date"].fillna(f["feature_id"].map(first_seen))

    known = set(f["feature_id"])
    for label, tbl in (("usage_monthly.csv", u), ("engineering_logs.csv", e)):
        unknown = set(tbl["feature_id"]) - known
        if unknown:
            warnings.append(f"{label}: {len(unknown)} feature_id(s) not in catalog were ignored.")
    u = u[u["feature_id"].isin(known)].sort_values(["feature_id", "month"]).reset_index(drop=True)
    e = e[e["feature_id"].isin(known)].sort_values(["feature_id", "month"]).reset_index(drop=True)

    # ---------------- feedback ----------------
    if feedback is not None and len(feedback):
        fb = _clean_columns(feedback, "feedback")
        _require(fb, "feedback")
        fb["text"] = fb["text"].fillna("").astype(str).str.strip()
        fb = fb[fb["text"].str.len() > 2].copy()
        if "ticket_id" not in fb.columns:
            fb["ticket_id"] = [f"T{i + 1:05d}" for i in range(len(fb))]
        fb["ticket_id"] = fb["ticket_id"].astype(str)
        fb["feature_id"] = fb["feature_id"].fillna("").astype(str).str.strip() if "feature_id" in fb.columns else ""
        fb.loc[~fb["feature_id"].isin(known), "feature_id"] = ""
        fb["source"] = fb["source"].fillna("Unknown").astype(str) if "source" in fb.columns else "Unknown"
        fb["customer_tier"] = fb["customer_tier"].fillna("").astype(str) if "customer_tier" in fb.columns else ""
        fb["created_at"] = pd.to_datetime(fb["created_at"], errors="coerce") if "created_at" in fb.columns else pd.NaT
        fb = fb.reset_index(drop=True)
    else:
        warnings.append("No feedback.csv - feedback mining and friction signals are disabled.")
        fb = pd.DataFrame(columns=["ticket_id", "feature_id", "source", "created_at", "customer_tier", "text"])

    return Dataset(features=f.reset_index(drop=True), usage=u, engineering=e, feedback=fb, name=name, warnings=warnings)


def load_folder(folder: str | Path, name: str | None = None) -> Dataset:
    folder = Path(folder)
    frames = {}
    for table, fname in FILENAMES.items():
        p = folder / fname
        frames[table] = pd.read_csv(p) if p.exists() else None
    if frames["features"] is None:
        raise DataValidationError(f"{folder / 'features.csv'} not found")
    return normalise(frames["features"], frames["usage"], frames["engineering"], frames["feedback"],
                     name=name or folder.name)


def load_uploads(files: dict[str, bytes], name: str = "uploaded") -> Dataset:
    """`files` maps table name (features/usage/engineering/feedback) -> raw CSV bytes."""
    frames: dict[str, pd.DataFrame | None] = {t: None for t in TABLES}
    for table, raw in files.items():
        if raw:
            try:
                frames[table] = pd.read_csv(io.BytesIO(raw))
            except Exception as exc:  # noqa: BLE001
                raise DataValidationError(f"Could not parse {FILENAMES.get(table, table)}: {exc}") from exc
    if frames["features"] is None:
        raise DataValidationError("features.csv is required")
    return normalise(frames["features"], frames["usage"], frames["engineering"], frames["feedback"], name=name)


def from_synthetic(ds, name: str = "Synthetic SaaS (Nimbus CRM)") -> Dataset:
    return normalise(ds.features, ds.usage, ds.engineering, ds.feedback, name=name)

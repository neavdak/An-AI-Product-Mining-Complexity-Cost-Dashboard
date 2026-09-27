import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        for _ in range(120):
            if c.get("/api/status").json()["status"] in ("ready", "error"):
                break
            time.sleep(0.25)
        yield c


def test_status_ready(client):
    s = client.get("/api/status").json()
    assert s["status"] == "ready", s
    assert s["dataset"]["n_features"] == 42


def test_analysis_and_params(client):
    r = client.get("/api/analysis", params={"roi_threshold": 30, "normalization": "minmax"})
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["params"]["roi_threshold"] == 30
    assert len(j["features"]) == 42
    assert client.get("/api/analysis", params={"roi_threshold": 500}).status_code == 422


def test_feature_detail_and_404(client):
    d = client.get("/api/features/F010").json()
    assert d["feature"]["feature_id"] == "F010" and d["usage"] and d["engineering"]
    assert client.get("/api/features/NOPE").status_code == 404


def test_feedback_endpoints(client):
    assert client.get("/api/feedback/clusters").json()["clusters"]
    t = client.get("/api/feedback/tickets", params={"category": "Performance Issue", "limit": 5}).json()
    assert t["total"] > 0 and all(i["category"] == "Performance Issue" for i in t["items"])
    m = client.get("/api/feedback/map").json()
    assert len(m["x"]) == len(m["y"]) > 0
    assert client.get("/api/feedback/heatmap").json()["z"]
    assert client.get("/api/series").json()["months"]


def test_memo_and_exports(client):
    assert "## Headline" in client.get("/api/memo").json()["markdown"]
    assert client.get("/api/export/features.csv").text.startswith("feature_id")
    assert client.get("/api/export/tickets.csv").status_code == 200
    assert client.get("/api/datasets/template/features").status_code == 200


def test_upload_validation(client):
    r = client.post("/api/datasets/upload", files={"features": ("f.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert r.status_code == 422


def test_frontend_served(client):
    assert "Complexity" in client.get("/").text
    assert client.get("/vendor/plotly.min.js").status_code == 200

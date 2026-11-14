"""GigSim behaviour: auth, idempotency, dry-run, policy v2, rate limits, client decisions."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def sim(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGSIM_DB", str(tmp_path / "sim.sqlite"))
    monkeypatch.setenv("GIGSIM_SEED_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("GIGSIM_API_TOKEN", "dev-gigsim-token")
    monkeypatch.setenv("GIGSIM_ADMIN_TOKEN", "dev-gigsim-admin")
    monkeypatch.setenv("GIGSIM_ERROR_RATE", "0")
    monkeypatch.setenv("GIGSIM_POST_COMMIT_ERROR_RATE", "0")
    monkeypatch.setenv("GIGSIM_GRADER", "heuristic")
    monkeypatch.setenv("GIGSIM_DISABLE_LOOP", "1")
    monkeypatch.setenv("GIGSIM_RATE_LIMIT_PER_MIN", "1000")
    import gigsim.app as mod

    mod = importlib.reload(mod)
    with TestClient(mod.app) as c:
        c.headers["Authorization"] = "Bearer dev-gigsim-token.ai_ml_engineer"
        yield c, mod


ADMIN = {"X-Admin-Token": "dev-gigsim-admin"}

LETTER = (
    "Your churn baseline needs honest evaluation on an imbalanced target. In my retail churn "
    "project I compared logistic regression and random forest with scikit-learn, reported "
    "precision/recall at 3 thresholds and lifted recall by 18% using class weights."
)


def test_auth_required(sim):
    c, _ = sim
    assert c.get("/v1/jobs", headers={"Authorization": ""}).status_code == 401


def test_search_hides_gold_and_applies_filters(sim):
    c, _ = sim
    items = c.get("/v1/jobs", params={"q": "churn"}).json()["items"]
    assert [j["id"] for j in items] == ["job_s1"]
    assert "gold" not in items[0]


def test_create_submit_idempotent_and_dry_run(sim):
    c, _ = sim
    body = {
        "job_id": "job_s1",
        "cover_letter": LETTER,
        "bid_amount": 400,
        "idempotency_key": "k-create-0001",
    }
    a = c.post("/v1/proposals", json=body).json()
    b = c.post("/v1/proposals", json=body).json()
    assert a == b  # replay returns the same draft
    pid = a["id"]
    preview = c.post(
        f"/v1/proposals/{pid}/submit", json={"idempotency_key": "k-submit-0001", "dry_run": True}
    ).json()
    assert preview["dry_run"] and preview["connects_cost"] == 8
    before = c.get("/v1/connects").json()["balance"]
    r1 = c.post(f"/v1/proposals/{pid}/submit", json={"idempotency_key": "k-submit-0001"}).json()
    r2 = c.post(f"/v1/proposals/{pid}/submit", json={"idempotency_key": "k-submit-0001"}).json()
    assert r1 == r2
    assert c.get("/v1/connects").json()["balance"] == before - 8  # spent exactly once


def test_policy_v2_surcharge_and_disclosure(sim):
    c, _ = sim
    assert c.get("/v1/jobs/job_s3").json()["connects_cost"] == 12
    c.post("/admin/policy", json={"version": 2}, headers=ADMIN)
    assert c.get("/v1/jobs/job_s3").json()["connects_cost"] == 16
    d = c.post(
        "/v1/proposals",
        json={
            "job_id": "job_s1",
            "cover_letter": LETTER,
            "bid_amount": 400,
            "idempotency_key": "k-create-0002",
        },
    ).json()
    r = c.post(f"/v1/proposals/{d['id']}/submit", json={"idempotency_key": "k-submit-0002"})
    assert r.status_code == 422 and "missing_ai_disclosure" in str(r.json())


def test_off_platform_message_blocked(sim):
    c, _ = sim
    d = c.post(
        "/v1/proposals",
        json={
            "job_id": "job_s1",
            "cover_letter": LETTER + " Email me at a@b.com",
            "bid_amount": 400,
            "idempotency_key": "k-create-0003",
        },
    ).json()
    r = c.post(f"/v1/proposals/{d['id']}/submit", json={"idempotency_key": "k-submit-0003"})
    assert r.status_code == 422


def test_client_decision_produces_events(sim):
    c, _ = sim
    d = c.post(
        "/v1/proposals",
        json={
            "job_id": "job_s1",
            "cover_letter": LETTER,
            "bid_amount": 400,
            "idempotency_key": "k-create-0004",
        },
    ).json()
    c.post(f"/v1/proposals/{d['id']}/submit", json={"idempotency_key": "k-submit-0004"})
    c.post("/admin/advance", json={"minutes": 300}, headers=ADMIN)
    c.post("/admin/advance", json={"minutes": 60 * 24 * 4}, headers=ADMIN)
    types = {e["type"] for e in c.get("/v1/events").json()["items"]}
    assert "submitted" in types and ({"replied", "lost"} & types)


def test_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGSIM_DB", str(tmp_path / "s.sqlite"))
    monkeypatch.setenv("GIGSIM_SEED_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("GIGSIM_API_TOKEN", "dev-gigsim-token")
    monkeypatch.setenv("GIGSIM_ERROR_RATE", "0")
    monkeypatch.setenv("GIGSIM_DISABLE_LOOP", "1")
    monkeypatch.setenv("GIGSIM_RATE_LIMIT_PER_MIN", "3")
    import gigsim.app as mod

    mod = importlib.reload(mod)
    with TestClient(mod.app) as c:
        h = {"Authorization": "Bearer dev-gigsim-token.ai_ml_engineer"}
        codes = [c.get("/v1/connects", headers=h).status_code for _ in range(4)]
    assert codes[-1] == 429

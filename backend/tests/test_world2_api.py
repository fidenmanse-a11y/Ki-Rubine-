"""World 2.0 HTTP API (rules-only residents in tests)."""
import pytest
from fastapi.testclient import TestClient

from rubine.main import app

PW = "test-password-123"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"password": PW}).status_code == 200
        yield client


def test_requires_auth():
    with TestClient(app) as anon:
        assert anon.get("/api/world2/state").status_code == 401
        assert anon.post("/api/world2/control", json={"action": "start"}).status_code == 401


def test_state_map_and_inspector(c):
    st = c.get("/api/world2/state").json()
    assert st["population"] == 25 and len(st["agents"]) == 25 and "calendar" in st
    m = c.get("/api/world2/map").json()
    assert len(m["terrain"]) == m["h"] and len(m["terrain"][0]) == m["w"]
    aid = st["agents"][0]["id"]
    d = c.get(f"/api/world2/agents/{aid}").json()
    assert d["simulated"] is True and "Simuliert" in d["notice"]
    for key in ("personality", "needs", "health", "wealth", "relations", "goals", "memories", "bio", "decisions", "model"):
        assert key in d


def test_controls_and_persistence(c):
    assert c.post("/api/world2/control", json={"action": "speed", "speed": 100}).json()["speed"] == 100
    assert c.post("/api/world2/control", json={"action": "pause"}).json()["running"] is False
    saved = c.post("/api/world2/control", json={"action": "save"}).json()["saved"]
    assert saved["snapshot_kb"] > 0
    backup = c.post("/api/world2/control", json={"action": "backup"}).json()["backup"]
    assert backup.endswith(".db")
    st = c.get("/api/world2/control").json()
    assert st["store"]["snapshots"] >= 1 and st["running"] is False
    assert c.post("/api/world2/control", json={"action": "speed", "speed": 7}).status_code == 422


def test_model_policy_only_allows_tested_versions(c):
    from rubine.db import ModelVersion, session_scope
    with session_scope() as s:
        s.merge(ModelVersion(id="rv-7777", name="ungetestet", status="failed_eval", base_model="x"))
    r = c.post("/api/world2/control", json={"action": "model_policy", "default_model": "rv-7777"})
    assert r.status_code == 422
    r = c.post("/api/world2/control", json={"action": "model_policy", "default_model": "base"})
    assert r.status_code == 200 and r.json()["model"]["default"] == "base"


def test_views(c):
    for path in ("/api/world2/society", "/api/world2/economy", "/api/world2/history", "/api/world2/events?limit=5",
                 "/api/world2/agents?include_dead=true"):
        assert c.get(path).status_code == 200, path
    eco = c.get("/api/world2/economy").json()
    assert eco["audit"]["ok"] is True


def test_new_separate_world(c):
    before = c.get("/api/world2/control").json()
    r = c.post("/api/world2/control", json={"action": "new_world", "name": "Zweite Welt", "seed": 4242}).json()
    after = c.get("/api/world2/control").json()
    assert after["active"] == r["created"]["id"] != before["active"]
    assert len(after["worlds"]) == len(before["worlds"]) + 1
    assert c.post("/api/world2/control", json={"action": "switch_world", "world_id": before["active"]}).status_code == 200

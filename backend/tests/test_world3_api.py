"""World 3.0 HTTP API: inspector mind state, people, society 3.0, interiors, follow, agent chat (auth + engine guard)."""
import pytest
from fastapi.testclient import TestClient

from rubine.main import app

PW = "test-password-123"


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"password": PW}).status_code == 200
        # let the world run a few simulated days so there is something to show
        from rubine.world2 import engine
        from rubine.world2 import rules as R
        from rubine.world2.service import get_service
        s = get_service()
        with s.lock:
            engine.run_ticks(s.world, 4 * R.TICKS_PER_DAY)
        yield client


def test_new_endpoints_require_auth():
    with TestClient(app) as anon:
        for path in ("/api/world2/people", "/api/world2/society3", "/api/world2/follow", "/api/world2/agents/A0001/mind"):
            assert anon.get(path).status_code == 401, path
        assert anon.post("/api/world2/agents/A0001/chat", json={"message": "hi"}).status_code == 401
        assert anon.post("/api/world2/follow", json={"agent_id": "A0001"}).status_code == 401


def test_inspector_mind(c):
    aid = c.get("/api/world2/state").json()["agents"][0]["id"]
    d = c.get(f"/api/world2/agents/{aid}").json()
    m = d["mind"]
    assert m["available"] and "keine nachgewiesenen Gefühle" in m["notice"]
    for key in ("agenda", "emotions", "mood", "beliefs", "opinions", "lessons", "morals", "reasoning", "goal_history",
                "friends", "promises", "secrets", "separation", "decision_sources"):
        assert key in m, key
    assert m["secrets"]["developer_only"] is True
    assert set(m["separation"]) == {"memory", "lessons", "model"}
    if m["agenda"]:
        g = m["agenda"][0]
        assert g["plan"]["steps"] and {"text", "expect", "done", "known"} <= set(g["plan"]["steps"][0])
    assert c.get(f"/api/world2/agents/{aid}/mind").json()["reasoning"] == m["reasoning"]
    assert c.get("/api/world2/agents/NOPE/mind").status_code == 404


def test_people_filters_and_follow(c):
    allp = c.get("/api/world2/people").json()
    assert allp["count"] == len(allp["people"]) >= 20
    q = allp["people"][0]["name"]
    assert all(q.lower() in (p["name"]).lower() for p in c.get(f"/api/world2/people?q={q}").json()["people"])
    aid = allp["people"][0]["id"]
    assert c.post("/api/world2/follow", json={"agent_id": aid}).json()["follow"][-1] == aid
    followed = c.get("/api/world2/people?filter=verfolgt").json()["people"]
    assert [p["id"] for p in followed] == [aid]
    assert c.post("/api/world2/follow", json={"agent_id": aid, "follow": False}).json()["follow"] == []
    assert c.post("/api/world2/follow", json={"agent_id": "NOPE"}).status_code == 404
    for f in ("gefangen", "krank", "kind", "amt", "obdachlos", "verstorben"):
        assert c.get(f"/api/world2/people?filter={f}").status_code == 200


def test_society3_and_map_traffic(c):
    s = c.get("/api/world2/society3").json()
    for key in ("justice", "alliances", "feuds", "promises", "rumors", "education", "settlements", "friendships"):
        assert key in s
    assert {"verdicts", "wrongful_convictions", "overturned_wrongful", "imprisonments", "appeals"} <= set(s["justice"]["totals"])
    m = c.get("/api/world2/map").json()
    assert m["traffic"] is not None and len(m["traffic"]) == m["h"]
    assert any(ch != "0" for row in m["traffic"] for ch in row)  # residents have walked around


def test_interior_matches_state(c):
    from rubine.world2.service import get_service
    s = get_service()
    with s.lock:
        w = s.world
        b = next(iter(w.buildings.values()))
        a = next(iter(w.living()))
        a["x"], a["y"], a["path"] = b["x"], b["y"], []
    r = c.get(f"/api/world2/buildings/{b['id']}/interior").json()
    inside = [p["id"] for room in r["rooms"] for p in room["people"]]
    assert a["id"] in inside and r["rooms"]
    assert c.get("/api/world2/buildings/NOPE/interior").status_code == 404


def test_agent_chat_requires_ready_model(c):
    from rubine.llm.engine import get_engine
    aid = c.get("/api/world2/state").json()["agents"][0]["id"]
    r = c.post(f"/api/world2/agents/{aid}/chat", json={"message": "Wie geht es dir?"})
    if get_engine().status != "ready":
        assert r.status_code == 503  # no fake replies without a model
    else:
        assert r.status_code == 200 and "event: done" in r.text

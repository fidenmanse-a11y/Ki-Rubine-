"""HTTP API tests (auth, chat with real streaming from the tiny model, lab safety rules)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from rubine.llm.engine import get_engine
from rubine.main import app
from rubine.security.auth import login_limiter

PW = "test-password-123"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        t = time.time()
        while get_engine().status != "ready" and time.time() - t < 60:
            time.sleep(0.2)
        assert get_engine().status == "ready", get_engine().error
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200
    return client


def sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
        if ev:
            out.append((ev, data))
    return out


def test_health_is_public_and_minimal(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"ok", "version", "auth_configured", "model_status"}


@pytest.mark.parametrize("path", ["/api/chat/conversations", "/api/lab/overview", "/api/lab/jobs", "/api/models",
                                  "/api/info", "/api/lab/stream"])
def test_private_endpoints_require_auth(path):
    with TestClient(app) as c:
        assert c.get(path).status_code == 401


def test_training_endpoints_require_auth():
    with TestClient(app) as c:
        assert c.post("/api/lab/jobs/train", json={}).status_code == 401
        assert c.post("/api/lab/versions/base/activate").status_code == 401
        assert c.post("/api/lab/data/synthetic", json={"n": 1}).status_code == 401


def test_login_rate_limit():
    login_limiter.reset("testclient")
    with TestClient(app) as c:
        for _ in range(5):
            assert c.post("/api/auth/login", json={"password": "falsch"}).status_code == 401
        assert c.post("/api/auth/login", json={"password": PW}).status_code == 429
    login_limiter.reset("testclient")


def test_cross_origin_post_rejected(auth):
    r = auth.post("/api/chat/conversations", json={}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_forged_token_rejected():
    with TestClient(app) as c:
        c.cookies.set("rubine_session", "eyJzdWIiOiJvd25lciJ9.forged")
        assert c.get("/api/chat/conversations").status_code == 401


def test_chat_flow_streams_real_tokens(auth):
    cid = auth.post("/api/chat/conversations", json={}).json()["id"]
    r = auth.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Hallo Rubine", "temperature": 0})
    events = sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds
    streamed = "".join(d["t"] for e, d in events if e == "token")
    conv = auth.get(f"/api/chat/conversations/{cid}").json()
    assert conv["title"] == "Hallo Rubine"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["content"] == streamed and conv["messages"][1]["model_version_id"] == "base"
    assert conv["messages"][1]["stats"]["tokens"] > 0

    # regenerate replaces the last answer
    r = auth.post(f"/api/chat/conversations/{cid}/regenerate", json={"temperature": 0})
    assert sse(r.text)[-1][0] == "done"
    assert len(auth.get(f"/api/chat/conversations/{cid}").json()["messages"]) == 2

    # edit the user message -> truncates and regenerates
    uid = conv["messages"][0]["id"]
    r = auth.post(f"/api/chat/messages/{uid}/edit", json={"content": "Neue Frage", "temperature": 0})
    assert sse(r.text)[-1][0] == "done"
    msgs = auth.get(f"/api/chat/conversations/{cid}").json()["messages"]
    assert msgs[0]["content"] == "Neue Frage" and len(msgs) == 2

    # search, rename, delete
    assert any(c["id"] == cid for c in auth.get("/api/chat/search", params={"q": "Neue Frage"}).json())
    assert auth.patch(f"/api/chat/conversations/{cid}", json={"title": "Umbenannt"}).json()["title"] == "Umbenannt"
    assert auth.delete(f"/api/chat/conversations/{cid}").status_code == 200
    assert auth.get(f"/api/chat/conversations/{cid}").status_code == 404


def test_feedback_requires_consent(auth):
    cid = auth.post("/api/chat/conversations", json={}).json()["id"]
    auth.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Test", "temperature": 0})
    aid = auth.get(f"/api/chat/conversations/{cid}").json()["messages"][1]["id"]
    r = auth.post(f"/api/chat/messages/{aid}/feedback", json={"value": 1})
    assert r.json()["proposed_for_training"] is False  # no consent
    auth.patch(f"/api/chat/conversations/{cid}", json={"training_consent": True})
    auth.post(f"/api/chat/messages/{aid}/feedback", json={"value": 0})
    r = auth.post(f"/api/chat/messages/{aid}/feedback", json={"value": 1})
    proposed = r.json()["proposed_for_training"]
    pending = auth.get("/api/lab/data/examples", params={"status": "pending", "source": "user_chat"}).json()
    assert proposed == (len(pending) == 1)
    # withdrawing consent deletes the proposals
    auth.patch(f"/api/chat/conversations/{cid}", json={"training_consent": False})
    assert auth.get("/api/lab/data/examples", params={"status": "pending", "source": "user_chat"}).json() == []


def test_unapproved_versions_not_selectable(auth):
    from rubine.db import ModelVersion, session_scope
    with session_scope() as s:
        s.merge(ModelVersion(id="rv-8888", name="ungetestet", status="failed_eval", base_model="x"))
    cid = auth.post("/api/chat/conversations", json={}).json()["id"]
    r = auth.post(f"/api/chat/conversations/{cid}/messages", json={"content": "x", "model_version_id": "rv-8888"})
    assert r.status_code == 400
    assert auth.post("/api/lab/versions/rv-8888/activate").status_code == 409


def test_lab_overview_and_validation(auth):
    ov = auth.get("/api/lab/overview").json()
    assert ov["active_version"]["id"] and "system" in ov and "cpu_percent" in ov["system"]
    assert auth.post("/api/lab/jobs/train", json={"lora_r": 1000}).status_code == 422
    assert auth.post("/api/lab/data/synthetic", json={"n": 5, "families": ["unbekannt"]}).status_code == 422
    assert auth.post("/api/lab/data/seeds/import", json={"name": "../../etc/passwd.jsonl"}).status_code in (404, 422)


def test_engine_unavailable_gives_clear_error(auth):
    eng = get_engine()
    old = eng.status
    eng.status = "error"
    eng.error = "Testfehler"
    try:
        cid = auth.post("/api/chat/conversations", json={}).json()["id"]
        r = auth.post(f"/api/chat/conversations/{cid}/messages", json={"content": "x"})
        assert r.status_code == 503 and "Testfehler" in r.json()["detail"]
        assert auth.get(f"/api/chat/conversations/{cid}").json()["messages"] == []  # nothing fabricated
    finally:
        eng.status, eng.error = old, None

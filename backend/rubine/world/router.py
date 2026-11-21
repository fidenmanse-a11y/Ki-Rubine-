"""Rubine World API + live stream (SSE)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Memory, WorldEvent, WorldTask, get_db
from ..security.auth import require_auth
from .simulation import World, clock, get_world
from .town import PERSONA

router = APIRouter(prefix="/api/world", dependencies=[Depends(require_auth)])


def _world() -> World:
    if not get_settings().sim_enabled:
        raise HTTPException(503, "Simulation ist deaktiviert (RUBINE_SIM_ENABLED=false)")
    return get_world()


@router.get("/map")
def world_map() -> dict:
    return World.static_map()


@router.get("/state")
def state() -> dict:
    return _world().snapshot(with_events=40)


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str, s: Session = Depends(get_db)) -> dict:
    w = _world()
    if agent_id not in PERSONA:
        raise HTTPException(404, "Agent nicht gefunden")
    p = PERSONA[agent_id]
    with w.lock:
        a = w.agents[agent_id]
        st = {"x": a.x, "y": a.y, "location": a.location, "activity": a.activity, "status": a.status, "plan": a.plan,
              "stats": dict(a.stats), "speech": a.speech}
    mems = s.scalars(select(Memory).where(Memory.agent_id == agent_id).order_by(Memory.id.desc()).limit(60))
    return {"persona": p.to_dict(), "state": st,
            "memories": [{"id": m.id, "kind": m.kind, "content": m.content, "importance": m.importance,
                          "clock": clock(m.sim_time)["label"]} for m in mems]}


@router.get("/events")
def events(limit: int = 100, kind: str | None = None, s: Session = Depends(get_db)) -> list[dict]:
    q = select(WorldEvent).order_by(WorldEvent.id.desc()).limit(min(limit, 500))
    if kind:
        q = q.where(WorldEvent.kind == kind)
    return [{"id": e.id, "kind": e.kind, "content": e.content, "agents": e.agents, "clock": clock(e.sim_time)["label"],
             "data": e.data} for e in s.scalars(q)]


@router.get("/tasks")
def tasks(limit: int = 30, s: Session = Depends(get_db)) -> list[dict]:
    rows = s.scalars(select(WorldTask).order_by(WorldTask.created_at.desc()).limit(min(limit, 200)))
    return [{"id": t.id, "family": t.family, "prompt": t.prompt, "status": t.status, "team": t.team,
             "proposals": t.proposals, "review": t.review, "outcome": t.outcome, "clock": clock(t.sim_time)["label"]}
            for t in rows]


class Control(BaseModel):
    action: str = Field(pattern="^(pause|resume|speed|task)$")
    tick_seconds: float | None = None


@router.post("/control")
def control(body: Control) -> dict:
    w = _world()
    if body.action == "pause":
        w.pause()
    elif body.action == "resume":
        w.resume()
    elif body.action == "speed" and body.tick_seconds:
        w.set_speed(body.tick_seconds)
    elif body.action == "task":
        if w.current_task and w.current_task.get("stage") != "done":
            raise HTTPException(409, "Es läuft bereits eine Aufgabe")
        ok, why = w.mind.available()
        if not ok:
            raise HTTPException(503, f"Keine Aufgabe möglich: {why}")
        w.current_task = None
        if w.post_task() is None:
            raise HTTPException(409, "Gerade nicht genug freie Agenten")
    return {"running": w.running, "tick_seconds": w.tick_seconds}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    w = _world()

    async def gen():
        last_version = -1
        last_event = 0
        idle = 0
        yield f"event: map\ndata: {json.dumps(World.static_map())}\n\n"
        while not await request.is_disconnected():
            if w.version != last_version:
                snap = w.snapshot()
                last_version = snap["version"]
                with w.lock:
                    new_events = [e for e in w.events if e.get("id", 0) > last_event]
                if new_events:
                    last_event = new_events[-1].get("id", last_event)
                snap["events"] = new_events[-20:]
                yield f"event: state\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
            else:
                idle += 1
                if idle % 20 == 0:
                    yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

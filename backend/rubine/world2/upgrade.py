"""Migrate saved World 2.0 snapshots to the World 3.0 schema (adds new state with neutral defaults)."""
from __future__ import annotations

import numpy as np

from .cognition import init_agent
from .state import World


def upgrade(w: World) -> World:
    if w.config.get("schema", 2) >= 3 and "traffic" in w.map:
        for a in w.agents.values():
            init_agent(w, a)
        return w
    if "traffic" not in w.map:
        w.map["traffic"] = np.zeros((w.h, w.w), dtype=np.int32)
    for a in w.agents.values():
        init_agent(w, a)
    w.config.setdefault("follow", [])
    w.config["schema"] = 3
    w.emit("system", "upgrade", "Welt auf World 3.0 aktualisiert: Ziele, Pläne, Emotionen, Überzeugungen und soziale Mechanik "
           "starten für bestehende Bewohner mit neutralen Werten.", witnesses=False)
    return w

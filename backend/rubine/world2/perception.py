"""Perception (agents only know what they have seen or been told) and movement (A* pathfinding)."""
from __future__ import annotations

import heapq

import numpy as np

from . import rules as R
from .mapgen import T, TERRAIN_CODES
from .state import World

RES_TYPES = ("wood", "stone", "fish", "forage", "herbs")
MOVE_COST = np.array([R.TERRAINS[name][2] for name in TERRAIN_CODES], dtype=np.float32)


def perceive(w: World, a: dict, radius: int = 4) -> None:
    """Record resource spots and buildings within sight into the agent's own map knowledge."""
    x, y = a["x"], a["y"]
    x0, x1, y0, y1 = max(0, x - radius), min(w.w, x + radius + 1), max(0, y - radius), min(w.h, y + radius + 1)
    known = a["known"]
    for res in RES_TYPES:
        sub = w.map[res][y0:y1, x0:x1]
        lst = known["res"].setdefault(res, [])
        # forget spots that are visibly exhausted
        lst[:] = [p for p in lst if not (x0 <= p[0] < x1 and y0 <= p[1] < y1 and w.map[res][p[1], p[0]] <= 0)]
        ys, xs = np.nonzero(sub > 0)
        if len(xs):
            order = np.argsort(-sub[ys, xs])[:3]
            for i in order:
                p = [int(xs[i] + x0), int(ys[i] + y0)]
                if p not in lst:
                    lst.append(p)
        if len(lst) > 8:
            lst.sort(key=lambda p: abs(p[0] - x) + abs(p[1] - y))
            del lst[8:]
    for b in w.buildings.values():
        if x0 <= b["x"] < x1 and y0 <= b["y"] < y1 and b["id"] not in known["bld"]:
            known["bld"].append(b["id"])
    if len(known["bld"]) > 80:
        known["bld"] = [bid for bid in known["bld"] if bid in w.buildings][-80:]


def known_spots(w: World, a: dict, res: str) -> list[list[int]]:
    return [p for p in a["known"]["res"].get(res, []) if w.map[res][p[1], p[0]] > 0]


def nearest(points: list, x: int, y: int):
    best, bd = None, 10**9
    for p in points:
        d = abs(p[0] - x) + abs(p[1] - y)
        if d < bd:
            best, bd = p, d
    return best, bd


def step_cost(w: World, x: int, y: int) -> float:
    if w.map["road"][y, x]:
        return 0.5
    t = int(w.map["terrain"][y, x])
    if t in (T["water"], T["river"]):
        return 1.0 if w.map["bridge"][y, x] else 999.0
    return float(MOVE_COST[t])


def find_path(w: World, start: tuple[int, int], goal: tuple[int, int], max_nodes: int = 6000) -> list[list[int]] | None:
    """A* on the tile grid. Returns the list of steps (excluding start) or None if unreachable."""
    if start == goal:
        return []
    gx, gy = goal
    if not w.passable(gx, gy):
        # accept an adjacent passable tile (e.g. fishing next to water)
        cands = [(gx + dx, gy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                 if w.in_bounds(gx + dx, gy + dy) and w.passable(gx + dx, gy + dy)]
        if not cands:
            return None
        cands.sort(key=lambda p: abs(p[0] - start[0]) + abs(p[1] - start[1]))
        gx, gy = cands[0]
        if (gx, gy) == start:
            return []
    openh = [(0.0, start)]
    came: dict[tuple[int, int], tuple[int, int]] = {}
    g = {start: 0.0}
    n = 0
    while openh and n < max_nodes:
        _, cur = heapq.heappop(openh)
        n += 1
        if cur == (gx, gy):
            path = []
            while cur != start:
                path.append([cur[0], cur[1]])
                cur = came[cur]
            return path[::-1]
        cx, cy = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if not w.in_bounds(nx, ny):
                continue
            c = step_cost(w, nx, ny)
            if c >= 999:
                continue
            ng = g[cur] + c
            if ng < g.get((nx, ny), 1e18):
                g[(nx, ny)] = ng
                came[(nx, ny)] = cur
                heapq.heappush(openh, (ng + abs(nx - gx) + abs(ny - gy), (nx, ny)))
    return None


def move_along(w: World, a: dict, points: float = 2.0) -> bool:
    """Advance on the stored path. Returns True when the destination is reached."""
    budget = points
    while a["path"] and budget > 0:
        nx, ny = a["path"][0]
        c = step_cost(w, nx, ny)
        if c >= 999:  # world changed (bridge collapsed)
            a["path"] = []
            return False
        if c > budget and budget < points:
            break
        budget -= c
        a["x"], a["y"] = nx, ny
        a["path"].pop(0)
    return not a["path"]

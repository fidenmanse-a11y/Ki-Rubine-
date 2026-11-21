"""Deterministic terrain generation (seeded): elevation, climate, lake, river, regions, resources."""
from __future__ import annotations

import numpy as np

W, H = 72, 48
TERRAIN_CODES = ["water", "river", "mountain", "hill", "forest", "meadow", "fertile", "steppe", "tundra", "clearing"]
T = {name: i for i, name in enumerate(TERRAIN_CODES)}

REGION_NAMES = ["Nordwald", "Seeufer", "Hochland", "Flusstal", "Südsteppe", "Westhain", "Osthügel", "Mittelau"]


def _noise(rng: np.random.Generator, w: int, h: int, octaves: int = 4) -> np.ndarray:
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 3 * (2 ** o)
        grid = rng.random((cells + 2, cells + 2))
        ys = np.linspace(0, cells, h)
        xs = np.linspace(0, cells, w)
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        a = grid[y0][:, x0]
        b = grid[y0][:, x0 + 1]
        c = grid[y0 + 1][:, x0]
        d = grid[y0 + 1][:, x0 + 1]
        layer = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
        out += layer * amp
        total += amp
        amp *= 0.5
    out /= total
    return (out - out.min()) / (out.max() - out.min() + 1e-9)


def generate(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    elev = _noise(rng, W, H)
    # mountains towards the north-east, lowland towards the south-west (gives rivers a direction)
    yy, xx = np.mgrid[0:H, 0:W]
    elev = 0.7 * elev + 0.3 * (1 - (yy / H) * 0.6 - (1 - xx / W) * 0.4)
    elev = (elev - elev.min()) / (elev.max() - elev.min())
    moist = _noise(rng, W, H, 3)

    terrain = np.full((H, W), T["meadow"], dtype=np.int8)
    lake_thr = np.quantile(elev, 0.06)
    terrain[elev <= lake_thr] = T["water"]
    terrain[elev >= 0.82] = T["mountain"]
    terrain[(elev >= 0.68) & (elev < 0.82)] = T["hill"]
    land = (terrain == T["meadow"])
    north = yy < H * 0.22
    south = yy > H * 0.78
    terrain[land & north & (moist < 0.45)] = T["tundra"]
    terrain[land & south & (moist < 0.5)] = T["steppe"]
    terrain[land & (moist > 0.55) & (terrain == T["meadow"])] = T["forest"]
    terrain[land & north & (moist >= 0.45)] = T["forest"]

    # river: from a high source downhill until water or border
    rivers = []
    lake_pts = np.argwhere(terrain == T["water"])
    ly, lx = (lake_pts.mean(0) if len(lake_pts) else (H - 1, W // 2))
    for _ in range(2):
        cand = np.argwhere((elev > 0.78) & (terrain != T["water"]))
        if len(cand) == 0:
            break
        y, x = cand[rng.integers(len(cand))]
        path, seen = [], set()
        for _step in range(400):
            path.append((int(x), int(y)))
            seen.add((int(x), int(y)))
            if terrain[y, x] == T["water"]:
                break
            nbrs = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < W and 0 <= y + dy < H and (x + dx, y + dy) not in seen]
            if not nbrs:
                break
            nbrs.sort(key=lambda p: 0.5 * elev[p[1], p[0]] + 0.5 * (abs(p[0] - lx) + abs(p[1] - ly)) / (W + H)
                      + rng.random() * 0.01)
            x, y = nbrs[0]
        for (px, py) in path:
            if terrain[py, px] != T["water"]:
                terrain[py, px] = T["river"]
        rivers.append(path)
    # fertile floodplain next to rivers/lake
    water_mask = (terrain == T["river"]) | (terrain == T["water"])
    near = np.zeros_like(water_mask)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            near |= np.roll(np.roll(water_mask, dy, 0), dx, 1)
    terrain[near & np.isin(terrain, [T["meadow"], T["steppe"], T["forest"]]) & (elev < 0.68)] = T["fertile"]

    # resources
    wood = np.where(terrain == T["forest"], 30 + (moist * 20).astype(int), 0)
    stone = np.where(terrain == T["mountain"], 160, np.where(terrain == T["hill"], 50, 0))
    fish = np.where(terrain == T["water"], 25, np.where(terrain == T["river"], 12, 0))
    forage = np.select([terrain == T["fertile"], terrain == T["meadow"], terrain == T["forest"], terrain == T["steppe"]],
                       [8, 6, 4, 2], 0)
    herbs = np.where(np.isin(terrain, [T["forest"], T["meadow"], T["fertile"]]) & (rng.random((H, W)) < 0.25), 5, 0)
    fertility = np.select([terrain == T["fertile"], terrain == T["meadow"], terrain == T["clearing"], terrain == T["steppe"]],
                          [1.0, 0.65, 0.6, 0.35], 0.0)

    # regions (Voronoi over seeds) – geographic labels only
    seeds = []
    for i in range(7):
        while True:
            sx, sy = int(rng.integers(4, W - 4)), int(rng.integers(4, H - 4))
            if all(abs(sx - a) + abs(sy - b) > 14 for a, b in seeds):
                seeds.append((sx, sy))
                break
    dist = np.stack([np.abs(xx - sx) + np.abs(yy - sy) for sx, sy in seeds])
    region = dist.argmin(0).astype(np.int8)
    names = []
    pool = list(REGION_NAMES)
    for i, (sx, sy) in enumerate(seeds):
        mask = region == i
        tcount = {k: int((terrain[mask] == v).sum()) for k, v in T.items()}
        if tcount["water"] > mask.sum() * 0.2:
            pref = "Seeufer"
        elif tcount["mountain"] + tcount["hill"] > mask.sum() * 0.35:
            pref = "Hochland" if "Hochland" in pool else "Osthügel"
        elif tcount["river"] + tcount["fertile"] > mask.sum() * 0.2:
            pref = "Flusstal"
        elif tcount["steppe"] > mask.sum() * 0.3:
            pref = "Südsteppe"
        elif tcount["forest"] + tcount["tundra"] > mask.sum() * 0.4:
            pref = "Nordwald" if "Nordwald" in pool else "Westhain"
        else:
            pref = pool[0]
        name = pref if pref in pool else pool[0]
        pool.remove(name)
        names.append(name)

    # starting area: fertile/meadow tile near water in the middle band
    cand = np.argwhere(np.isin(terrain, [T["fertile"], T["meadow"]]) & (yy > H * 0.3) & (yy < H * 0.7) & near)
    if len(cand) == 0:
        cand = np.argwhere(np.isin(terrain, [T["fertile"], T["meadow"]]))
    cy, cx = cand[rng.integers(len(cand))]
    return {
        "w": W, "h": H, "terrain": terrain, "elev": elev.astype(np.float32), "moist": moist.astype(np.float32),
        "wood": wood.astype(np.int32), "stone": stone.astype(np.int32), "fish": fish.astype(np.int32),
        "forage": forage.astype(np.int32), "herbs": herbs.astype(np.int32), "fertility": fertility.astype(np.float32),
        "region": region, "region_names": names, "start": (int(cx), int(cy)),
    }

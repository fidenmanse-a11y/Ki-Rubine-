"""Economy: personal valuations, barter and currency trade, market prices, taxes, gifts, jobs, loans, money.

Prices are not set by the engine: every trade price comes from the two parties'
reservation values (which depend on needs, stocks, personality) and bargaining.
Money only exists after residents adopt a currency through an institution; its
supply is created by a documented minting rule and recorded in the ledger.
"""
from __future__ import annotations

import math

from . import rules as R
from .state import World, clamp

TARGET_STOCK = {"food": 8, "wood": 6, "stone": 4, "herbs": 3, "tools": 1, "medicine": 1}


def coin_item(cid: str) -> str:
    return f"coin:{cid}"


def region_currency(w: World, region: int) -> dict | None:
    for c in w.currencies.values():
        if c["region"] == region and c["active"]:
            return c
    return None


def stock(w: World, a: dict, item: str) -> int:
    n = w.qty(("agent", a["id"]), item)
    h = w.buildings.get(a.get("home") or "")
    if h:
        n += int((h.get("inv") or {}).get(item, 0))
    return n


def food_days(w: World, a: dict) -> float:
    eaters = 1 + sum(1 for c in a["children"] if c in w.agents and w.agents[c]["alive"] and w.age(w.agents[c]) < 12)
    return stock(w, a, "food") / (2.0 * eaters)


def market_price(w: World, region: int, item: str) -> float:
    return float(w.markets.get(str(region), {}).get(item, {}).get("price", R.BASE_VALUE.get(item, 1.0)))


def coin_value(w: World, region: int, cid: str) -> float:
    """Food-equivalents per coin, derived from observed food-for-coin trades (starts at 1)."""
    p = w.markets.get(str(region), {}).get(f"food@{cid}", {}).get("price")
    return 1.0 / p if p else 1.0


def valuation(w: World, a: dict, item: str) -> float:
    """Value of one more unit to this agent, in food-equivalents. Needs and stocks matter; personality tilts."""
    if item.startswith("coin:"):
        cid = item.split(":", 1)[1]
        return coin_value(w, w.home_region(a), cid) * (0.85 + 0.3 * a["values"]["wealth"])
    have = stock(w, a, item)
    v = R.BASE_VALUE[item]
    n = a["needs"]
    if item == "food":
        v *= 1 + 1.6 * n["hunger"] + 1.2 * max(0.0, 4 - food_days(w, a)) / 4
    elif item == "wood":
        v *= 1 + (0.6 if w.season >= 2 else 0) + (0.8 if a.get("building_plan") else 0)
    elif item == "stone":
        v *= 1 + (0.8 if a.get("building_plan") else 0)
    elif item == "medicine":
        v *= 1 + (3 * a["illness"]["severity"] if a.get("illness") else 0) + (0.5 if a["skills"]["healing"] > 0.3 else 0)
    elif item == "herbs":
        v *= 1 + (0.6 if "kraeuterkunde" in a["techs"] else -0.3)
    elif item == "tools":
        v *= 1.3 if have == 0 else 0.4
    if have > TARGET_STOCK.get(item, 5):
        v *= 0.55
    return max(0.05, v * (0.85 + 0.3 * a["values"]["wealth"]))


def honesty(a: dict) -> float:
    p = a["personality"]
    return clamp(0.45 * p["agreeableness"] + 0.35 * p["conscientiousness"] + 0.2 * p["self_control"])


def _tradeables(w: World, a: dict) -> list[str]:
    items = [k for k, v in (a.get("inv") or {}).items() if v > 0]
    return items


def propose_trade(w: World, a: dict, b: dict) -> dict | None:
    """Find a mutually beneficial exchange (a gives `give`, receives `get`). None if no gain for both."""
    best = None
    for get in [i for i in _tradeables(w, b)]:
        if get.startswith("coin:") and get not in (a.get("inv") or {}) and not _usable_coin(w, a, get):
            continue
        va_get, vb_get = valuation(w, a, get), valuation(w, b, get)
        if va_get <= vb_get * 1.05:
            continue
        for give in _tradeables(w, a):
            if give == get:
                continue
            if give.startswith("coin:") and not _usable_coin(w, b, give):
                continue
            va_give, vb_give = valuation(w, a, give), valuation(w, b, give)
            max_ratio = va_get / va_give      # units of `give` a would pay per unit of `get`
            min_ratio = vb_get / vb_give      # units b requires
            if max_ratio < min_ratio:
                continue
            gain = (max_ratio - min_ratio) * va_give
            if best is None or gain > best["gain"]:
                best = {"get": get, "give": give, "min": min_ratio, "max": max_ratio, "gain": gain}
    if not best:
        return None
    # bargaining: share of surplus depends on ambition/trading skill of each side
    pa = 0.5 + 0.3 * (a["personality"]["ambition"] - b["personality"]["ambition"]) + 0.2 * (a["skills"]["trading"] - b["skills"]["trading"])
    ratio = best["max"] - (best["max"] - best["min"]) * clamp(pa, 0.1, 0.9)
    q_get = 1
    have_get = w.qty(("agent", b["id"]), best["get"])
    want = 3 if best["get"] == "food" and a["needs"]["hunger"] > 0.5 else 2
    q_get = max(1, min(have_get, want))
    q_give = max(1, math.ceil(q_get * ratio - 1e-9))
    while q_give > w.qty(("agent", a["id"]), best["give"]) and q_get > 1:
        q_get -= 1
        q_give = max(1, math.ceil(q_get * ratio - 1e-9))
    if q_give > w.qty(("agent", a["id"]), best["give"]) or q_get > have_get:
        return None
    # both must still gain at integer quantities
    if q_give * valuation(w, a, best["give"]) > q_get * valuation(w, a, best["get"]) * 1.02:
        return None
    if q_get * valuation(w, b, best["get"]) > q_give * valuation(w, b, best["give"]) * 1.02:
        return None
    return {"give": best["give"], "q_give": q_give, "get": best["get"], "q_get": q_get}


def _usable_coin(w: World, a: dict, coin: str) -> bool:
    cid = coin.split(":", 1)[1]
    c = w.currencies.get(cid)
    return bool(c and c["active"] and c["region"] == w.home_region(a))


def execute_trade(w: World, a: dict, b: dict, deal: dict, cause: int | None = None) -> int:
    from .society import active_law, treasury_of
    region = w.region_of(a["x"], a["y"])
    q_get = deal["q_get"]
    cheat = None
    # the delivering side (b) may short-deliver if dishonest and desperate/greedy (a choice, not random noise)
    if q_get >= 2 and honesty(b) < 0.32 and w.rng.random() < (0.35 - honesty(b)) * 2:
        q_get -= 1
        cheat = b["id"]
    w.transfer(("agent", a["id"]), ("agent", b["id"]), deal["give"], deal["q_give"])
    w.transfer(("agent", b["id"]), ("agent", a["id"]), deal["get"], q_get)
    # tax on the payment, if a tax law is in force in this region
    tax_law = active_law(w, region, "steuer")
    tax = 0
    if tax_law:
        rate = float(tax_law["effect"]["params"].get("satz", 0.1))
        tax = int(deal["q_give"] * rate + w.rng.random())
        tax = min(tax, w.qty(("agent", b["id"]), deal["give"]))
        inst = treasury_of(w, region)
        if tax and inst:
            w.transfer(("agent", b["id"]), ("inst", inst["id"]), deal["give"], tax)
    for x in (a, b):
        x["skills"]["trading"] = round(min(1.0, x["skills"]["trading"] + 0.003), 4)
        x["stats"]["trades"] = x["stats"].get("trades", 0) + 1
    _record_price(w, region, deal["get"], deal["give"], deal["q_give"] / max(1, deal["q_get"]))
    w.daily["trades"] += 1
    w.adjust_rel(a["id"], b["id"], trust=0.03, familiarity=0.03, note="Tausch")
    w.adjust_rel(b["id"], a["id"], trust=0.03, familiarity=0.03, note="Tausch")
    text = (f"{a['name']} tauscht mit {b['name']}: {deal['q_give']} {_label(deal['give'])} gegen "
            f"{deal['q_get']} {_label(deal['get'])}" + (f" (Abgabe {tax})" if tax else "") + ".")
    eid = w.emit("wirtschaft", "tausch", text, actors=[a["id"], b["id"]], x=a["x"], y=a["y"],
                 data={**deal, "tax": tax, "region": region}, cause=cause)
    from .cognition import notify
    for x, other in ((a, b), (b, a)):
        w.learn(x, f"ev:{eid}", "event", text, "beobachtet", 1.0, ref=eid)
        notify(w, x, "tausch_ok", other=other["id"])
    if cheat:
        w.totals["fraud"] += 1
        fe = w.emit("justiz", "betrug", f"{b['name']} hat {a['name']} beim Tausch 1 {_label(deal['get'])} zu wenig gegeben.",
                    actors=[b["id"], a["id"]], x=a["x"], y=a["y"], public=False, witnesses=False, cause=eid,
                    data={"offender": b["id"], "victim": a["id"], "item": deal["get"], "qty": 1})
        a.setdefault("pending_discoveries", []).append({"type": "betrug", "event": fe, "offender": b["id"],
                                                         "due": w.tick + w.rng.randint(2, 30), "item": deal["get"]})
    return eid


def _label(item: str) -> str:
    if item.startswith("coin:"):
        return "Münzen"
    return R.ITEM_LABEL.get(item, item)


def _record_price(w: World, region: int, item: str, unit: str, ratio: float) -> None:
    """Price of `item` in units of `unit`. Stored in food-equivalents and per currency."""
    mk = w.markets.setdefault(str(region), {})
    if unit.startswith("coin:"):
        key = f"{item}@{unit.split(':', 1)[1]}"
        old = mk.get(key, {}).get("price")
        mk[key] = {"price": round(ratio if old is None else 0.7 * old + 0.3 * ratio, 3), "tick": w.tick,
                   "n": mk.get(key, {}).get("n", 0) + 1}
        return
    if item.startswith("coin:"):
        return
    in_food = ratio * (market_price(w, region, unit) if unit != "food" else 1.0)
    old = mk.get(item, {}).get("price")
    mk[item] = {"price": round(in_food if old is None else 0.7 * old + 0.3 * in_food, 3), "tick": w.tick,
                "n": mk.get(item, {}).get("n", 0) + 1}


def give(w: World, a: dict, b: dict, item: str, n: int, *, reason: str = "hilfe") -> int:
    n = min(n, w.qty(("agent", a["id"]), item))
    if n <= 0:
        return 0
    w.transfer(("agent", a["id"]), ("agent", b["id"]), item, n)
    w.adjust_rel(b["id"], a["id"], trust=0.08, affection=0.08, familiarity=0.05, note=f"Hilfe ({n} {_label(item)})")
    w.adjust_rel(a["id"], b["id"], affection=0.04, familiarity=0.04)
    eid = w.emit("sozial", "hilfe", f"{a['name']} gibt {b['name']} {n} {_label(item)}.", actors=[a["id"], b["id"]],
                 x=a["x"], y=a["y"], data={"item": item, "n": n, "reason": reason})
    w.remember(b, "sozial", f"{a['name']} hat mir mit {n} {_label(item)} geholfen.", 6, event=eid, subjects=[a["id"]],
               tags=["hilfe"])
    from .cognition import notify
    notify(w, b, "geholfen", other=a["id"])
    w.remember(a, "sozial", f"Ich habe {b['name']} mit {n} {_label(item)} geholfen.", 4, event=eid, subjects=[b["id"]])
    a["stats"]["helped"] = a["stats"].get("helped", 0) + 1
    w.daily["help"] += 1
    return n


def wealth(w: World, a: dict) -> float:
    total = 0.0
    region = w.home_region(a)
    for it, n in (a.get("inv") or {}).items():
        if it.startswith("coin:"):
            total += n * coin_value(w, region, it.split(":", 1)[1])
        else:
            total += n * R.BASE_VALUE.get(it, 1)
    for b in w.buildings.values():
        if b.get("owner") == a["id"]:
            total += sum(R.BASE_VALUE.get(i, 1) * q for i, q in R.BUILDINGS[b["type"]]["mat"].items()) * b["condition"]
            total += sum(n * R.BASE_VALUE.get(i, 1) for i, n in (b.get("inv") or {}).items() if not i.startswith("coin:"))
    return round(total, 2)


def gini(values: list[float]) -> float:
    v = sorted(max(0.0, x) for x in values)
    n = len(v)
    if n == 0 or sum(v) == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return round((2 * cum) / (n * sum(v)) - (n + 1) / n, 3)


# ------------------------------------------------------------------ employment
def wage_offer(w: World, owner: dict) -> tuple[str, int] | None:
    c = region_currency(w, w.home_region(owner))
    if c and w.qty(("agent", owner["id"]), coin_item(c["id"])) >= 9:
        per_food = max(1, round(1 / max(0.1, coin_value(w, w.home_region(owner), c["id"]))))
        return coin_item(c["id"]), max(1, int(round(3 * per_food * (1.2 - 0.4 * owner["personality"]["ambition"]))))
    if stock(w, owner, "food") >= 9:
        return "food", 3 if owner["personality"]["agreeableness"] > 0.5 else 2
    return None


def hire(w: World, owner: dict, worker: dict, building: dict, wage: tuple[str, int]) -> dict:
    cid = w.new_id("C")
    c = {"id": cid, "type": "arbeit", "employer": owner["id"], "worker": worker["id"], "building": building["id"],
         "wage_item": wage[0], "wage": wage[1], "start": w.tick, "status": "aktiv", "missed": 0, "paid_days": 0}
    w.contracts[cid] = c
    worker["employer"] = cid
    eid = w.emit("wirtschaft", "arbeitsvertrag", f"{owner['name']} stellt {worker['name']} ein "
                 f"({wage[1]} {_label(wage[0])} pro Tag, {R.BUILDINGS[building['type']]['label']}).",
                 actors=[owner["id"], worker["id"]], x=owner["x"], y=owner["y"], data={"contract": cid})
    c["event"] = eid
    return c


def end_contract(w: World, c: dict, reason: str) -> None:
    c["status"] = reason
    wk = w.agents.get(c.get("worker") or "")
    if wk and wk.get("employer") == c["id"]:
        wk["employer"] = None


def pay_wages(w: World) -> None:
    """Daily at 18:00: employers pay. Missing payment is a contract breach with consequences."""
    from .society import open_case
    for c in list(w.contracts.values()):
        if c["type"] != "arbeit" or c["status"] != "aktiv":
            continue
        emp, wk = w.agents.get(c["employer"]), w.agents.get(c["worker"])
        if not emp or not wk or not emp["alive"] or not wk["alive"] or c["building"] not in w.buildings:
            end_contract(w, c, "beendet")
            continue
        if not c.get("worked_today"):
            continue
        c["worked_today"] = False
        src = None
        for ref in (("agent", emp["id"]), ("building", c["building"])):
            if w.qty(ref, c["wage_item"]) >= c["wage"]:
                src = ref
                break
        if src:
            w.transfer(src, ("agent", wk["id"]), c["wage_item"], c["wage"])
            c["paid_days"] += 1
            w.daily["wages_paid"] += 1
        else:
            c["missed"] += 1
            eid = w.emit("wirtschaft", "lohn_ausgefallen", f"{emp['name']} konnte {wk['name']} den Lohn nicht zahlen.",
                         actors=[emp["id"], wk["id"]], x=emp["x"], y=emp["y"], public=False, witnesses=False,
                         data={"contract": c["id"]})
            w.learn(wk, f"ev:{eid}", "event", f"{emp['name']} hat meinen Lohn nicht gezahlt.", "beobachtet", 1.0, ref=eid)
            w.adjust_rel(wk["id"], emp["id"], trust=-0.12, note="Lohn nicht gezahlt", event=eid)
            wk["stressors"] = min(1.0, wk.get("stressors", 0) + 0.1)
            if c["missed"] >= 2:
                end_contract(w, c, "gebrochen")
                if wk["personality"]["conflict_avoidance"] < 0.6:
                    open_case(w, "vertragsbruch", accuser=wk, accused=emp, event=eid, evidence=[wk["id"]])


# ------------------------------------------------------------------ loans
def lend(w: World, lender: dict, borrower: dict, item: str, n: int) -> dict:
    interest = int(round(n * 0.4 * lender["personality"]["ambition"]))
    w.transfer(("agent", lender["id"]), ("agent", borrower["id"]), item, n)
    cid = w.new_id("C")
    c = {"id": cid, "type": "kredit", "lender": lender["id"], "borrower": borrower["id"], "item": item, "amount": n,
         "interest": interest, "due": w.tick + 7 * R.TICKS_PER_DAY, "status": "aktiv", "start": w.tick}
    w.contracts[cid] = c
    c["event"] = w.emit("wirtschaft", "kredit", f"{lender['name']} leiht {borrower['name']} {n} {_label(item)} "
                        f"(Rückzahlung {n + interest} in 7 Tagen).", actors=[lender["id"], borrower["id"]],
                        x=lender["x"], y=lender["y"], data={"contract": cid})
    return c


def repay(w: World, borrower: dict, c: dict) -> bool:
    lender = w.agents.get(c["lender"])
    due = c["amount"] + c["interest"]
    if w.qty(("agent", borrower["id"]), c["item"]) < due:
        return False
    if lender and lender["alive"]:
        w.transfer(("agent", borrower["id"]), ("agent", lender["id"]), c["item"], due)
        w.adjust_rel(lender["id"], borrower["id"], trust=0.1, note="Kredit zurückgezahlt")
    c["status"] = "bezahlt"
    w.emit("wirtschaft", "kredit_bezahlt", f"{borrower['name']} hat den Kredit zurückgezahlt.", actors=[borrower["id"], c["lender"]],
           x=borrower["x"], y=borrower["y"], data={"contract": c["id"]}, cause=c.get("event"))
    return True


def check_loans(w: World) -> None:
    from .society import open_case
    for c in w.contracts.values():
        if c["type"] == "kredit" and c["status"] == "aktiv" and w.tick > c["due"]:
            c["status"] = "ausgefallen"
            lender, borrower = w.agents.get(c["lender"]), w.agents.get(c["borrower"])
            if not lender or not borrower:
                continue
            eid = w.emit("wirtschaft", "zahlungsausfall", f"{borrower['name']} konnte den Kredit von {lender['name']} nicht "
                         "fristgerecht zurückzahlen.", actors=[borrower["id"], lender["id"]], x=borrower["x"], y=borrower["y"],
                         public=False, witnesses=False, data={"contract": c["id"]}, cause=c.get("event"))
            borrower["debts"] = borrower.get("debts", 0) + 1
            borrower["stressors"] = min(1.0, borrower.get("stressors", 0) + 0.2)
            if lender["alive"]:
                w.learn(lender, f"ev:{eid}", "event", f"{borrower['name']} hat meinen Kredit nicht zurückgezahlt.", "beobachtet", 1.0, ref=eid)
                w.adjust_rel(lender["id"], borrower["id"], trust=-0.12, note="Kredit nicht zurückgezahlt", event=eid)
                if lender["personality"]["conflict_avoidance"] < 0.5 and borrower["alive"]:
                    open_case(w, "vertragsbruch", accuser=lender, accused=borrower, event=eid, evidence=[lender["id"]])


# ------------------------------------------------------------------ currency
def introduce_currency(w: World, inst: dict, name: str, per_adult: int, cause: int | None) -> dict:
    cid = w.new_id("M")
    region = inst["region"]
    cur = {"id": cid, "name": name, "inst": inst["id"], "region": region, "active": True, "founded": w.tick,
           "minted": 0, "rule": f"Einmalige Ausgabe von {per_adult} Münzen je erwachsenem Mitglied"}
    w.currencies[cid] = cur
    item = coin_item(cid)
    members = w.adults(region)
    total = per_adult * len(members)
    w.produce(("inst", inst["id"]), item, total, f"münzung:{cid}")
    cur["minted"] += total
    for m in members:
        w.transfer(("inst", inst["id"]), ("agent", m["id"]), item, per_adult)
    eid = w.emit("wirtschaft", "waehrung", f"Die Währung '{name}' wurde eingeführt: {total} Münzen geprägt, "
                 f"je {per_adult} an {len(members)} Erwachsene.", x=None, y=None, cause=cause,
                 data={"currency": cid, "minted": total}, witnesses=False)
    for m in members:
        w.learn(m, f"cur:{cid}", "event", f"Neue Währung '{name}' gilt in {w.region_name(region)}.", "Aushang", 1.0, ref=eid)
    return cur

"""Rubine World 2.0: economy, society, residents, world, persistence and training export."""
import json
import random

import pytest

from rubine.world2 import actions as A
from rubine.world2 import construction as C
from rubine.world2 import economy as E
from rubine.world2 import engine
from rubine.world2 import rules as R
from rubine.world2 import society as S
from rubine.world2.genesis import create_world
from rubine.world2.life import kill
from rubine.world2.state import LedgerError, to_snapshot
from rubine.world2.store import WorldStore


@pytest.fixture
def w():
    return create_world("t", "Test", 7)


def _two(w):
    a, b = list(w.agents.values())[:2]
    b["x"], b["y"] = a["x"], a["y"]
    return a, b


# ------------------------------------------------------------------ world start
def test_world_starts_without_preset_society(w):
    assert len(w.living()) == 25
    assert not w.buildings and not w.institutions and not w.laws and not w.currencies
    assert all(a["home"] is None for a in w.living())
    assert len({a["origin"] for a in w.living()}) == 4
    assert all(set(a["personality"]) == set(R.PERSONALITY) for a in w.living())


# ------------------------------------------------------------------ economy
def test_ledger_conservation_over_simulation(w):
    engine.run_ticks(w, 6 * R.TICKS_PER_DAY)
    audit = w.audit()
    assert audit["ok"], audit
    assert sum(w.ledger["produced"].values()) > 0


def test_items_cannot_be_created_or_go_negative(w):
    a, b = _two(w)
    with pytest.raises(LedgerError):
        w.transfer(("agent", a["id"]), ("agent", b["id"]), "tools", 99)
    with pytest.raises(LedgerError):
        w.consume(("agent", a["id"]), "stone", 5, "test")
    assert w.audit()["ok"]


def test_gathering_depletes_the_tile(w):
    a = next(iter(w.agents.values()))
    x, y = a["x"], a["y"]
    w.map["forage"][y, x] = 3
    before = w.qty(("agent", a["id"]), "food")
    n = A._gain(w, a, "forage", "food", "gathering", 5.0, {"data": {}})
    assert n == 3 and w.map["forage"][y, x] == 0
    assert w.qty(("agent", a["id"]), "food") == before + 3
    assert w.audit()["ok"]


def test_trade_moves_exactly_the_agreed_goods(w):
    a, b = _two(w)
    a["inv"], b["inv"] = {"wood": 6}, {"food": 6}
    w.ledger["initial"] = __import__("collections").Counter(w.all_holdings())
    w.ledger["produced"].clear(); w.ledger["consumed"].clear()
    a["needs"]["hunger"] = 0.9
    b["personality"]["agreeableness"] = b["personality"]["conscientiousness"] = b["personality"]["self_control"] = 0.9
    deal = E.propose_trade(w, a, b)
    assert deal and deal["give"] == "wood" and deal["get"] == "food"
    E.execute_trade(w, a, b, deal)
    assert a["inv"]["food"] == deal["q_get"] and a["inv"].get("wood", 0) == 6 - deal["q_give"]
    assert b["inv"]["wood"] == deal["q_give"] and b["inv"].get("food", 0) == 6 - deal["q_get"]
    assert w.audit()["ok"]
    assert any(e["kind"] == "tausch" for e in w.event_buffer)


def test_no_trade_without_mutual_gain(w):
    a, b = _two(w)
    a["inv"], b["inv"] = {"food": 1}, {"food": 5}
    assert E.propose_trade(w, a, b) is None


def test_unpaid_wages_are_a_breach(w):
    a, b = _two(w)
    for x in (a, b):
        x["inv"] = {}
    site = C.start_site(w, "werkstatt", a["x"] + 1, a["y"], owner=a["id"])
    for it, n in site["need"].items():
        w.produce(("site", site["id"]), it, n, "test")
    site["labor_done"] = site["labor_needed"]
    bld = C.complete(w, site)
    b["personality"]["conflict_avoidance"] = 0.1
    c = E.hire(w, a, b, bld, ("food", 3))
    for _ in range(2):
        c["worked_today"] = True
        E.pay_wages(w)
    assert c["status"] == "gebrochen" and b["employer"] is None
    assert sum(1 for e in w.event_buffer if e["kind"] == "lohn_ausgefallen") == 2
    assert any(k["type"] == "vertragsbruch" for k in w.cases.values())
    assert w.rel(b["id"], a["id"])["trust"] < 0.5


def test_loan_default_is_recorded(w):
    a, b = _two(w)
    a["inv"], b["inv"] = {"food": 10}, {}
    w.ledger["initial"] = __import__("collections").Counter(w.all_holdings())
    w.ledger["produced"].clear(); w.ledger["consumed"].clear()
    c = E.lend(w, a, b, "food", 3)
    assert b["inv"]["food"] == 3
    w.tick = c["due"] + 1
    E.check_loans(w)
    assert c["status"] == "ausgefallen" and b.get("debts") == 1
    assert w.audit()["ok"]


# ------------------------------------------------------------------ society
def _idea(kind="gesetz"):
    return {"key": "law:eigentumsschutz", "kind": kind, "effect": {"type": "eigentumsschutz", "params": {"sanktion": "rueckgabe"}},
            "title": "Eigentum schützen", "weight": 1, "reason": "Test"}


def test_bootstrap_vote_rule_and_law_storage(w):
    voters = w.adults(w.home_region(next(iter(w.agents.values()))))
    p = S.make_proposal(w, voters[0], _idea())
    p["votes"] = {voters[0]["id"]: "ja", voters[1]["id"]: "ja", voters[2]["id"]: "nein"}
    w.tick = p["closes"]
    S.close_proposals(w)
    # 2 yes < max(3, 30% of adults) -> rejected under the founding rule
    assert p["status"] == "abgelehnt" and not w.laws
    p2 = S.make_proposal(w, voters[0], dict(_idea(), key="x"))
    need = max(R.BOOTSTRAP_MIN_YES, int(R.BOOTSTRAP_QUORUM * len(w.adults(p2["region"]))) + 1)
    p2["votes"] = {v["id"]: "ja" for v in voters[:need]}
    w.tick = p2["closes"]
    S.close_proposals(w)
    assert p2["status"] == "angenommen"
    law = next(iter(w.laws.values()))
    assert law["status"] == "aktiv" and law["effect"]["type"] == "eigentumsschutz" and law["proposal"] == p2["id"]
    assert any(e["kind"] == "gesetz" and e["cause"] == p2["result_event"] for e in w.event_buffer)


def test_council_rule_only_counts_council(w):
    first = next(iter(w.agents.values()))
    for x in w.agents.values():
        x["x"], x["y"] = first["x"], first["y"]
    region = w.home_region(first)
    adults = w.adults(region)
    gov = {"id": "I9999", "type": "regierung", "form": "rat", "name": "Rat", "region": region, "founded": 0, "founder": adults[0]["id"],
           "members": [a["id"] for a in adults], "leaders": [a["id"] for a in adults[:3]], "active": True, "legitimacy": 0.6,
           "inv": {}, "history": []}
    w.institutions[gov["id"]] = gov
    p = S.make_proposal(w, adults[5], dict(_idea(), key="y"))
    p["votes"] = {a["id"]: "ja" for a in adults[3:]}          # everyone outside the council says yes
    p["votes"].update({a["id"]: "nein" for a in adults[:3]})  # council says no
    w.tick = p["closes"]
    S.close_proposals(w)
    assert p["status"] == "abgelehnt"


def test_theft_creates_traceable_events_and_verdict(w):
    a, b = _two(w)
    witness = list(w.agents.values())[2]
    witness["x"], witness["y"] = a["x"], a["y"]
    witness["asleep"] = False
    b["inv"] = {"food": 5}
    w.ledger["initial"] = __import__("collections").Counter(w.all_holdings())
    w.ledger["produced"].clear(); w.ledger["consumed"].clear()
    region = w.home_region(b)
    w.institutions["I1"] = {"id": "I1", "type": "gericht", "name": "Gericht", "region": region, "founded": 0, "founder": witness["id"],
                            "members": [list(w.agents.values())[3]["id"]], "leaders": [], "active": True, "inv": {}}
    eid = S.steal(w, a, b, None, "food", 2)
    ev = next(e for e in w.event_buffer if e["id"] == eid)
    assert ev["public"] is False and ev["data"]["offender"] == a["id"]
    assert witness["facts"][f"ev:{eid}"]["src"] == "beobachtet"   # the witness actually saw it
    b["personality"]["conflict_avoidance"] = 0.1
    S.discover_offense(w, b, "diebstahl", a, eid, "food", 2, observed=False)
    case = next(iter(w.cases.values()))
    assert case["status"] == "behauptung"                        # an accusation is not a fact
    w.tick += R.TICKS_PER_DAY + 1
    S.daily_justice(w)
    assert case["status"] == "schuldig" and witness["id"] in case["evidence"] and case["matches_truth"] is True
    verdict = next(e for e in w.event_buffer if e["kind"] == "urteil")
    assert verdict["cause"] == case["claim_event"]
    assert w.audit()["ok"]


def test_false_accusation_without_evidence_is_acquitted(w):
    a, b = _two(w)
    innocent = list(w.agents.values())[4]
    region = w.home_region(b)
    w.institutions["I1"] = {"id": "I1", "type": "gericht", "name": "Gericht", "region": region, "founded": 0, "founder": b["id"],
                            "members": [list(w.agents.values())[5]["id"]], "leaders": [], "active": True, "inv": {}}
    b["inv"] = {"food": 4}
    eid = S.steal(w, a, b, None, "food", 1)
    case = S.open_case(w, "diebstahl", accuser=b, accused=innocent, event=None, evidence=[], claimed_event=eid)
    w.tick += R.TICKS_PER_DAY + 1
    S.daily_justice(w)
    assert case["status"] == "freigesprochen" and case["matches_truth"] is True


# ------------------------------------------------------------------ residents
def test_personality_influences_helping(w):
    a, b = _two(w)
    hungry = list(w.agents.values())[2]
    hungry["x"], hungry["y"] = a["x"] + 1, a["y"]
    hungry["needs"]["hunger"], hungry["inv"] = 0.95, {}
    us = {}
    for agree in (0.1, 0.9):
        a["personality"]["agreeableness"] = agree
        a["inv"] = {"food": 12}
        opts = [o for o in A.generate_options(w, a) if o["type"] == "help"]
        us[agree] = opts[0]["u"] if opts else 0
    assert us[0.9] > us[0.1] * 2


def test_choices_are_not_deterministic_perfect(w):
    a = next(iter(w.agents.values()))
    opts = [A.opt("x", "beste", 1.0), A.opt("y", "zweitbeste", 0.8)]
    a["personality"]["conscientiousness"] = 0.1
    picks = [A.choose(w, a, opts)["label"] for _ in range(300)]
    assert 0.2 < picks.count("zweitbeste") / 300 < 0.5


def test_conversation_shares_knowledge(w):
    a, b = _two(w)
    w.learn(a, "law:L1", "law", "Gesetz: Eigentum schützen", "Aushang", 1.0, ref="L1")
    S.converse(w, a, b)
    assert b["facts"]["law:L1"]["src"] == "Gerücht" and b["facts"]["law:L1"]["from"] == a["id"]


def test_dead_agents_never_act(w):
    a = next(iter(w.agents.values()))
    kill(w, a, "Test")
    pos = (a["x"], a["y"])
    engine.run_ticks(w, 50)
    assert not a["alive"] and (a["x"], a["y"]) == pos and a["action"] is None
    assert not any(d["agent"] == a["id"] and d["t"] > a["death_tick"] for d in w.decision_buffer)
    assert any(e["kind"] == "tod" and a["id"] in e["actors"] for e in w.event_buffer)


def test_memories_and_world_survive_restart(tmp_path, w):
    engine.run_ticks(w, 3 * R.TICKS_PER_DAY)
    a = next(x for x in w.living() if x["ltm"])
    store = WorldStore(tmp_path / "world.db")
    store.checkpoint(w)
    w2 = store.load_latest()
    assert w2.agents[a["id"]]["ltm"] == a["ltm"]
    assert set(w2.buildings) == set(w.buildings) and w2.tick == w.tick
    engine.run_ticks(w, 100)
    engine.run_ticks(w2, 100)
    assert json.dumps(to_snapshot(w), sort_keys=True, default=str) == json.dumps(to_snapshot(w2), sort_keys=True, default=str)


# ------------------------------------------------------------------ world
def test_buildings_require_materials_and_labor(w):
    a = next(iter(w.agents.values()))
    w.ledger["initial"]["wood"] += 2 - a["inv"].get("wood", 0)
    a["inv"]["wood"] = 2
    site = C.start_site(w, "huette", a["x"], a["y"], owner=a["id"])
    assert C.work_on(w, a, site, 50, 1.0) is None and site["labor_done"] == 0  # no materials, no progress
    C.deliver(w, a, site)
    assert C.missing_materials(site) == {"wood": 3}
    w.produce(("agent", a["id"]), "wood", 3, "test")
    C.deliver(w, a, site)
    b = C.work_on(w, a, site, R.BUILDINGS["huette"]["labor"], 1.0)
    assert b and b["type"] == "huette" and site["id"] not in w.sites and a["home"] == b["id"]
    assert w.ledger["consumed"]["wood"] >= 5 and w.audit()["ok"]


def test_invalid_plots_are_rejected(w):
    from rubine.world2.mapgen import T
    ys, xs = (w.map["terrain"] == T["water"]).nonzero()
    assert not C.valid_plot(w, "huette", int(xs[0]), int(ys[0]))


def test_calendar_is_consistent(w):
    c0 = w.calendar()
    engine.run_ticks(w, R.TICKS_PER_DAY)
    c1 = w.calendar()
    assert c1["day"] == c0["day"] + 1 and (c1["hour"], c1["minute"]) == (c0["hour"], c0["minute"])
    assert w.calendar(R.DAYS_PER_SEASON * R.TICKS_PER_DAY)["season"] == 1
    assert w.calendar(R.TICKS_PER_YEAR)["year"] == 2
    a = next(iter(w.agents.values()))
    age = w.age(a)
    w.tick += R.TICKS_PER_YEAR
    assert abs(w.age(a) - age - 1) < 1e-9


def test_births_create_new_individuals(w):
    a, b = _two(w)
    S.form_partnership(w, a, b)
    a["expecting"] = {"due": w.tick, "partner": b["id"]}
    from rubine.world2.life import process_births
    process_births(w)
    child = w.agents[a["children"][0]]
    assert child["parents"] == [a["id"], b["id"]] and child["generation"] == 1 and w.age(child) == 0
    assert child["personality"] != a["personality"] and child["id"] not in (a["id"], b["id"])


def test_long_run_is_stable():
    w = create_world("t2", "Lang", 11)
    engine.run_ticks(w, 30 * R.TICKS_PER_DAY)
    assert not w.errors, list(w.errors)[:2]
    assert w.audit()["ok"]
    assert w.buildings and w.config["stats_last"]["population"] >= 15


# ------------------------------------------------------------------ training export
def test_simulation_export_is_verified_and_excludes_eval():
    from rubine.db import Example, session_scope
    from rubine.training import curriculum as cur
    from rubine.training.evalset import eval_prompt_hashes
    from rubine.world2.export import all_tasks, export_to_pool
    w = create_world("t3", "Export", 5)
    engine.run_ticks(w, 8 * R.TICKS_PER_DAY)
    tasks = all_tasks(w, list(w.event_buffer))
    assert tasks and {t.family for t in tasks} >= {"sim_trade", "sim_supply"}
    assert all(cur.verify(t, t.solution)[0] for t in tasks)
    with session_scope() as s:
        res = export_to_pool(s, w, list(w.event_buffer), per_family=20)
        assert res["verified_tasks"] > 0
        rows = s.query(Example).filter(Example.source == "sim_gold").all()
        assert all(r.verified and r.status == "approved" for r in rows)
        assert not {r.prompt_hash for r in rows} & eval_prompt_hashes()

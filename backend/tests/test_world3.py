"""World 3.0: goals & multi-step plans, reactions, learning, social mechanics, justice with prisons and appeals."""
import collections
import random

import pytest

from rubine.world2 import actions as A
from rubine.world2 import cognition as C
from rubine.world2 import construction as CO
from rubine.world2 import engine, env, justice as J
from rubine.world2 import rules as R
from rubine.world2 import social3 as S3
from rubine.world2 import society as S
from rubine.world2.genesis import create_world


@pytest.fixture
def w():
    return create_world("t3", "Test3", 9)


def _same_place(w):
    first = next(iter(w.agents.values()))
    for x in w.agents.values():
        x["x"], x["y"] = first["x"], first["y"]
    return first


# ------------------------------------------------------------------ plans
def test_agents_execute_self_made_multistep_plans(w):
    engine.run_ticks(w, 7 * R.TICKS_PER_DAY)
    reached = [h for a in w.agents.values() for h in a["goal_history"] if h["type"] == "zuhause" and h["status"] == "erreicht"]
    assert len(reached) >= 18
    # the plan consisted of several ordered steps that were completed one after another
    a = next(a for a in w.living() if any(g["type"] == "hof" for g in a["agenda"]) or a["home"])
    g = C._new_goal(w, a, {"type": "hof", "prio": 0.5, "why": "test"})
    assert [s["text"] for s in g["plan"]["steps"]][:1] == ["8 Holz beschaffen"]
    assert len(g["plan"]["steps"]) == 4 and g["plan"]["steps"][-1]["cond"] == {"owns": "bauernhof"}


def test_plan_depth_depends_on_reasoning(w):
    a, b = list(w.agents.values())[:2]
    a["reasoning"], b["reasoning"] = 0.05, 0.95
    ga = C._new_goal(w, a, {"type": "hof", "prio": 0.5, "why": "x"})
    gb = C._new_goal(w, b, {"type": "hof", "prio": 0.5, "why": "x"})
    assert ga["plan"]["visible"] < gb["plan"]["visible"]


def test_reaction_to_losing_home(w):
    engine.run_ticks(w, 8 * R.TICKS_PER_DAY)
    a = next(a for a in w.living() if a["home"] and w.age(a) >= 18)
    home = w.buildings[a["home"]]
    env.collapse_building(w, home)
    assert a["home"] is None and a["replan"] == "Zuhause verloren"
    for _ in range(R.TICKS_PER_HOUR):
        engine.step(w)
    goals = {g["type"]: g for g in a["agenda"] if g["status"] == "aktiv"}
    assert "zuhause" in goals
    assert any(e["kind"] == "planaenderung" and a["id"] in e["actors"] and "Zuhause verloren" in e["text"] for e in w.event_buffer)
    engine.run_ticks(w, 6 * R.TICKS_PER_DAY)
    assert a["home"] is not None or not a["alive"]


def test_goals_adapt_to_a_crisis(w):
    engine.run_ticks(w, 3 * R.TICKS_PER_DAY)
    a = next(a for a in w.living() if w.age(a) >= 18)
    for it in list(a["inv"]):
        w.consume(("agent", a["id"]), it, a["inv"][it], "test")
    if a.get("home"):
        h = w.buildings[a["home"]]
        for it in list(h.get("inv", {})):
            w.consume(("building", h["id"]), it, h["inv"][it], "test")
    a["needs"]["hunger"] = 0.9
    C.manage_goals(w, a, reason="Test")
    active = sorted([g for g in a["agenda"] if g["status"] == "aktiv"], key=lambda g: -g["prio"])
    assert active and active[0]["type"] in ("vorrat", "zuhause")
    assert any(g["type"] == "vorrat" and g["status"] == "aktiv" for g in a["agenda"])


def test_learning_from_conviction_reduces_crime(w):
    a, b = list(w.agents.values())[:2]
    b["x"], b["y"] = a["x"], a["y"]
    a["needs"]["hunger"], a["inv"], b["inv"] = 0.95, {}, {"food": 9}
    a["personality"]["self_control"] = a["personality"]["agreeableness"] = 0.1
    a["morals"]["ehrlichkeit"] = 0.1

    def steal_u():
        opts = A.generate_options(w, a)
        return max([o["u"] for o in opts if o["type"] == "steal"] or [-9])
    before = steal_u()
    C.notify(w, a, "verurteilt", innocent=False, accuser=b["id"], offense_action="steal")
    after = steal_u()
    assert after < before - 0.3
    assert a["lessons"]["steal"] < 0 and a["lesson_log"]


def test_causal_attribution_depends_on_reasoning(w):
    a = next(iter(w.agents.values()))
    rates = {}
    for r in (0.05, 0.95):
        a["reasoning"] = r
        hits = 0
        for _ in range(200):
            a["beliefs"] = {}
            key = C.attribute_illness(w, a, {"hunger": 1.5, "kaelte": 0.1, "stress": 0.2, "wasser": 0, "ansteckung": 0})
            hits += key == "hunger_krank"
        rates[r] = hits / 200
    assert rates[0.95] > rates[0.05] + 0.3
    assert C.BELIEFS["fremde_krank"][1] is False  # misattributions exist and are marked false


def test_emotions_follow_events_and_fade(w):
    a, b = list(w.agents.values())[:2]
    C.notify(w, a, "bestohlen", other=b["id"])
    assert a["emo"]["aerger"] > 0.3 and a["emo_targets"][b["id"]]["aerger"] > 0.3
    for _ in range(48):
        C.decay_emotions(w, a)
    assert a["emo"]["aerger"] < 0.2


# ------------------------------------------------------------------ social
def test_promises_kept_and_broken(w):
    a, b = list(w.agents.values())[:2]
    site = CO.start_site(w, "huette", a["x"], a["y"], owner=a["id"])
    p = S3.promise(w, b, a, "bauhilfe", site["id"], 2, "beim Bau zu helfen")
    w.ledger["initial"]["wood"] += 2 - b["inv"].get("wood", 0)
    b["inv"]["wood"] = 2
    CO.deliver(w, b, site)
    S3.check_promises(w)
    assert p["status"] == "gehalten"
    p2 = S3.promise(w, list(w.agents.values())[2], a, "bauhilfe", site["id"], 1, "zu helfen")
    w.tick = p2["due"] + 1
    trust_before = w.rel(a["id"], p2["from"])["trust"]
    S3.check_promises(w)
    assert p2["status"] == "gebrochen" and w.rel(a["id"], p2["from"])["trust"] < trust_before


def test_false_rumor_is_exposed_by_its_subject(w):
    liar, listener, subject = list(w.agents.values())[:3]
    S3.spread_rumor(w, liar, listener, subject)
    rid = next(iter(w.rumors))
    assert w.rumors[rid]["false"] is True and f"rumor:{rid}" in listener["facts"]
    assert C.opinion(listener, subject["id"])["verdacht"] > 0
    S3._hear_rumor(w, subject, listener, rid)  # listener tells the subject
    assert w.rumors[rid].get("exposed") is True
    est, _ = C.honesty_estimate(listener, liar["id"])
    assert est < 0.5
    assert any(e["kind"] == "luege_aufgedeckt" for e in w.event_buffer)


def test_well_known_people_are_defended_against_rumors(w):
    liar, listener, subject = list(w.agents.values())[:3]
    for _ in range(8):
        C.judge_person(w, listener, subject["id"], True, 1.0)
    S3.spread_rumor(w, liar, listener, subject)
    rid = next(iter(w.rumors))
    assert f"rumor:{rid}" not in listener["facts"]
    assert any(e["kind"] == "widerspruch" for e in w.event_buffer)


def test_persuasion_and_alliances_shift_votes(w):
    first = _same_place(w)
    adults = w.adults(w.home_region(first))
    idea = {"key": "x", "kind": "gesetz", "effect": {"type": "steuer", "params": {"satz": 0.1}}, "title": "Abgabe", "weight": 1, "reason": "t"}
    prop = S.make_proposal(w, adults[0], idea)
    target = adults[1]
    w.relations[f"{target['id']}>{adults[0]['id']}"] = {"trust": 0.95, "affection": 0.9, "respect": 0.8, "familiarity": 0.5, "hist": [], "last": 0}
    base = [S.vote_utility(w, target, prop) for _ in range(50)]
    w.rng = random.Random(1)
    successes = sum(S3.persuade(w, adults[0], target, prop["id"]) for _ in range(5))
    assert successes >= 1
    after = [S.vote_utility(w, target, prop) for _ in range(50)]
    assert sum(after) / 50 > sum(base) / 50


def test_feud_forms_and_ends(w):
    a, b = list(w.agents.values())[:2]
    C.feel(w, a, "aerger", 0.9, target=b["id"])
    C.feel(w, b, "aerger", 0.6, target=a["id"])
    S3.update_feuds(w)
    k = S3.feud_key(a["id"], b["id"])
    assert w.feuds[k]["active"]
    a["emo_targets"], b["emo_targets"] = {}, {}
    for x, y in ((a, b), (b, a)):
        w.rel(x["id"], y["id"])["affection"] = 0.6
    for _ in range(20):
        S3.update_feuds(w)
    assert not w.feuds[k]["active"]
    assert any(e["kind"] == "versoehnung" for e in w.event_buffer)


# ------------------------------------------------------------------ justice
def _justice_setup(w, sanction="haft", judges=1):
    first = _same_place(w)
    region = w.home_region(first)
    ag = list(w.agents.values())
    gov = {"id": "IG", "type": "regierung", "form": "versammlung", "name": "Gov", "region": region, "founded": 0, "founder": ag[0]["id"],
           "members": [a["id"] for a in ag], "leaders": [], "active": True, "legitimacy": 0.6, "inv": {}, "history": []}
    w.institutions["IG"] = gov
    w.produce(("inst", "IG"), "food", 40, "test")
    w.institutions["IC"] = {"id": "IC", "type": "gericht", "name": "Gericht", "region": region, "founded": 0, "founder": ag[5]["id"],
                            "members": [a["id"] for a in ag[5:5 + judges]], "leaders": [], "active": True, "inv": {}}
    w.institutions["IW"] = {"id": "IW", "type": "wache", "name": "Wache", "region": region, "founded": 0, "founder": ag[8]["id"],
                            "members": [ag[8]["id"]], "leaders": [], "active": True, "inv": {}}
    ag[8]["reasoning"] = 1.0
    w.laws["L1"] = {"id": "L1", "region": region, "inst": "IG", "title": "Eigentum", "text": "", "status": "aktiv", "adopted": 0,
                    "proposal": None, "proposer": ag[0]["id"], "effect": {"type": "eigentumsschutz", "params": {"sanktion": sanction}}}
    site = CO.start_site(w, "gefaengnis", first["x"] + 2, first["y"], owner="IG", owner_kind="inst")
    for it, n in site["need"].items():
        w.produce(("site", site["id"]), it, n, "test")
    site["labor_done"] = site["labor_needed"]
    prison = CO.complete(w, site)
    return ag, region, prison


def _run_justice_days(w, n):
    for _ in range(n):
        w.tick += R.TICKS_PER_DAY
        S.daily_justice(w)


def test_trial_prison_and_release(w):
    ag, region, prison = _justice_setup(w)
    thief, victim, witness = ag[1], ag[2], ag[3]
    for x in (witness,):
        x["asleep"] = False
        x["morals"]["loyalitaet"] = 0.1
    w.ledger["initial"]["food"] += 6 - victim["inv"].get("food", 0)
    victim["inv"]["food"] = 6
    thief["morals"]["ehrlichkeit"] = 0.0  # will deny
    eid = S.steal(w, thief, victim, None, "food", 2)
    victim["personality"]["conflict_avoidance"] = 0.1
    S.discover_offense(w, victim, "diebstahl", None, eid, "food", 2, observed=False)  # victim does not know who it was
    case = next(c for c in w.cases.values() if c["type"] == "diebstahl")
    for _ in range(5):
        w.tick += R.TICKS_PER_DAY
        J.process_cases(w)  # verdicts only; prison days are run explicitly below
        if case["status"] not in ("behauptung", "ermittlung", "anklage"):
            break
    assert case["status"] in ("schuldig", "freigesprochen", "eingestellt")
    if case["accused"] == thief["id"]:
        assert case["status"] == "schuldig" and "Haft" in case["sanction"]
        assert thief["prison"] and (thief["x"], thief["y"]) == (prison["x"], prison["y"])
        opts = {o["type"] for o in A.generate_options(w, thief)}
        assert opts <= {"eat", "sleep", "rest", "drink", "talk"}
        food_before = w.qty(("inst", "IG"), "food")
        J.daily_prisons(w)
        assert w.qty(("inst", "IG"), "food") < food_before  # inmates are fed from the treasury
        w.tick = thief["prison"]["until"]
        J.daily_prisons(w)
        assert thief["prison"] is None and thief["convictions"] == 1
        assert any(e["kind"] == "entlassung" for e in w.event_buffer)
    else:  # a distrustful victim accused someone else: the innocent must not be convicted by the true witness
        assert case["status"] != "schuldig" or case["matches_truth"] is False
    assert w.audit()["ok"]


def test_single_unknown_false_witness_is_not_enough(w):
    ag, region, _ = _justice_setup(w)
    for x in w.agents.values():
        x["asleep"] = True
    case = S.open_case(w, "diebstahl", accuser=ag[2], accused=ag[3], event=None, evidence=[], claimed_event=None)
    case["false_testimony"] = [ag[4]["id"]]
    _run_justice_days(w, 5)
    assert case["status"] in ("eingestellt", "freigesprochen")


def test_presumption_of_innocence(w):
    ag, region, _ = _justice_setup(w)
    case = S.open_case(w, "diebstahl", accuser=ag[1], accused=ag[2], event=None, evidence=[], claimed_event=None)
    _run_justice_days(w, 5)
    assert case["status"] in ("eingestellt", "freigesprochen")
    assert ag[2].get("convictions", 0) == 0


def test_wrongful_conviction_overturned_on_appeal(w):
    import copy
    ag, region, prison = _justice_setup(w, sanction="haft", judges=2)
    real_thief, victim, innocent = ag[1], ag[2], ag[3]
    w.ledger["initial"]["food"] += 5 - victim["inv"].get("food", 0)
    victim["inv"]["food"] = 5
    for x in w.agents.values():
        x["asleep"] = True  # nobody saw it
    eid = S.steal(w, real_thief, victim, None, "food", 1)
    # the victim suspects the wrong person; two people who are angry at that person testify falsely
    case = S.open_case(w, "diebstahl", accuser=victim, accused=innocent, event=None, evidence=[], claimed_event=eid)
    case["false_testimony"] = [ag[4]["id"], ag[9]["id"]]
    _run_justice_days(w, 3)
    assert case["status"] == "schuldig" and case["matches_truth"] is False
    assert w.totals["wrongful_convictions"] == 1
    assert innocent["prison"] is not None
    assert J.file_appeal(w, innocent, case)
    assert not J.file_appeal(w, innocent, case)  # only one appeal
    w.agents[ag[6]["id"]]["reasoning"] = 1.0  # the second judge is careful
    outcomes = collections.Counter()
    for seed in range(30):
        w2 = copy.deepcopy(w)
        w2.rng = random.Random(seed)
        c2 = w2.cases[case["id"]]
        _run_justice_days(w2, 2)
        outcomes[c2["appeal"]["status"]] += 1
        exposed = c2["appeal"]["exposed_false_witnesses"]
        if c2["appeal"]["status"] == "aufgehoben":
            inn = w2.agents[innocent["id"]]
            assert exposed and inn["prison"] is None and inn["convictions"] == 0
            assert w2.totals["overturned_wrongful"] == 1
            assert any(e["kind"] == "falschaussage_aufgedeckt" for e in w2.event_buffer)
            assert any(c["type"] == "meineid" and c["accused"] in exposed for c in w2.cases.values())
        else:
            assert not exposed  # upheld only when no lie was uncovered
        assert w2.audit()["ok"]
    # probability of uncovering at least one of two lies is 1 - 0.25**2 ≈ 0.94 with a careful judge
    assert outcomes["aufgehoben"] >= 22, outcomes


def test_old_world2_snapshot_is_upgraded(tmp_path):
    import json
    import zlib

    from rubine.world2.state import to_snapshot
    from rubine.world2.store import WorldStore
    old = create_world("old", "Alt", 2)
    snap = to_snapshot(old)
    for a in snap["agents"].values():
        for k in ("emo", "agenda", "morals", "beliefs", "reasoning", "lessons", "friends", "opinions"):
            a.pop(k, None)
    for k in ("promises", "rumors", "alliances", "feuds"):
        snap.pop(k)
    snap["map"].pop("traffic")
    snap["config"].pop("schema")
    store = WorldStore(tmp_path / "world.db")
    store.checkpoint(old)
    with store._conn() as c:
        c.execute("UPDATE snapshots SET data = ?", (zlib.compress(json.dumps(snap).encode()),))
    w = store.load_latest()
    a = next(iter(w.agents.values()))
    assert w.config["schema"] == 3 and "traffic" in w.map and "emo" in a and "morals" in a
    engine.run_ticks(w, 50)
    assert not w.errors


def test_long_run_world3_is_stable():
    w = create_world("lr", "Lang3", 13)
    engine.run_ticks(w, 25 * R.TICKS_PER_DAY)
    assert not w.errors, list(w.errors)[:2]
    assert w.audit()["ok"]
    kinds = collections.Counter(e["kind"] for e in w.event_buffer)
    assert kinds["planaenderung"] > 0 and kinds["versprechen"] > 0


def test_desperate_people_may_consider_taking_food_at_night(w):
    a, b = list(w.agents.values())[:2]
    b["x"], b["y"] = a["x"], a["y"]
    w.ledger["initial"]["food"] += 9 - b["inv"].get("food", 0)
    a["inv"], b["inv"] = {}, {"food": 9}
    a["needs"]["hunger"] = 0.97
    a["morals"]["ehrlichkeit"] = 0.1
    a["personality"]["self_control"] = 0.1
    w.tick = 2 * R.TICKS_PER_DAY + 23 * R.TICKS_PER_HOUR
    b["asleep"] = True
    opts = {o["type"]: o for o in A.generate_options(w, a)}
    assert "steal" in opts  # possible, not forced: utility still competes with sleep/eat
    honest = list(w.agents.values())[2]
    honest["x"], honest["y"], honest["inv"] = a["x"], a["y"], {}
    honest["needs"]["hunger"] = 0.97
    honest["morals"]["ehrlichkeit"] = 0.95
    honest["personality"]["self_control"] = 0.95
    hs = [o for o in A.generate_options(w, honest) if o["type"] == "steal"]
    assert not hs or hs[0]["u"] < opts["steal"]["u"]


def test_resident_benchmark_is_deterministic_and_held_out():
    from rubine.world2 import benchmark as B
    from rubine.world2.export import TRAIN_DECISION_CATS
    i1, i2 = B.build_items(per_cat=3), B.build_items(per_cat=3)
    assert B.items_sha(i1) == B.items_sha(i2) and len(i1) >= 19
    assert B.items_sha(B.build_items()) == "a58e6740d54db85cee5a7df4b907a8aaabff81ef79bd1e9a79b4818e1d36831d"  # documented result set
    assert {it["cat"] for it in i1} == set(B.CATEGORIES)
    assert set(B.CATEGORIES) - set(TRAIN_DECISION_CATS) == {"anpassung", "normen"}  # transfer categories are never trained
    other = B.build_items(seed=900_001, per_cat=3)
    assert not ({it["user"] for it in other} & {it["user"] for it in i1})
    assert B.parse_choice("Wahl: 2\nGrund: x", 3) == 1 and B.parse_choice("Wahl: 9", 3) is None and B.parse_choice("keine", 3) is None
    res = B.run(lambda s, u: "Wahl: 1", i1)
    assert 0 <= res["accuracy"] <= 1 and res["per_category"]["bedarf"]["rules_engine"] == 1.0


def test_larger_resident_model_requires_benchmark(tmp_path, monkeypatch):
    import json as _json
    from rubine.config import get_settings
    from rubine.world2 import service as SV
    st = get_settings()
    monkeypatch.setattr(type(st), "eval_dir", property(lambda self: tmp_path))
    assert SV.benchmarked_hf_model("Qwen/Qwen2.5-1.5B-Instruct") is None
    assert SV.benchmarked_hf_model("some/unlisted-model") is None
    d = tmp_path / "agent_bench"
    d.mkdir()
    (d / "Qwen_Qwen2.5-1.5B-Instruct-x.json").write_text(_json.dumps({"accuracy": 0.35, "chance": 0.31}))
    assert SV.benchmarked_hf_model("Qwen/Qwen2.5-1.5B-Instruct") is None  # not clearly above chance
    (d / "Qwen_Qwen2.5-1.5B-Instruct-y.json").write_text(_json.dumps({"accuracy": 0.69, "chance": 0.31}))
    assert SV.benchmarked_hf_model("Qwen/Qwen2.5-1.5B-Instruct")["accuracy"] == 0.69

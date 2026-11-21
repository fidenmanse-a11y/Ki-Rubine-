"""Real LoRA training on the tiny model: loss must go down, pause/resume must work."""

import os

import pytest
from sqlalchemy import delete

from rubine.config import get_settings
from rubine.db import EvalRun, Example, Job, ModelVersion, session_scope
from rubine.jobs import manager as jm
from rubine.jobs import runner
from rubine.llm import registry
from rubine.training import data as D
from rubine.training.evaluate import evaluate_items, promotion_gate
from rubine.training.trainer import TrainConfig, TrainingInterrupted, train_lora

ROWS = [{"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": f"Frage {i % 4}"},
                      {"role": "assistant", "content": f"Die Antwort ist {i % 4}.\nAntwort: {i % 4}"}]} for i in range(32)]


def test_lora_training_mechanics(tmp_path):
    """Tiny random model: only checks that optimisation runs and moves the loss downward."""
    cfg = TrainConfig(max_steps=30, epochs=10, batch_size=4, learning_rate=2e-2, lora_r=8, seed=1, save_every=0)
    summary = train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "out", ckpt_dir=tmp_path / "ck")
    assert summary["steps"] == 30
    assert summary["mean_loss_last10"] < summary["mean_loss_first10"]
    assert (tmp_path / "out" / "adapter_model.safetensors").exists()
    assert summary["trainable_params"] < summary["total_params"] * 0.2


def test_training_is_reproducible(tmp_path):
    cfg = TrainConfig(max_steps=5, batch_size=4, learning_rate=1e-3, seed=3, save_every=0)
    a = train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "a", ckpt_dir=tmp_path / "ca")
    b = train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "b", ckpt_dir=tmp_path / "cb")
    assert a["final_loss"] == pytest.approx(b["final_loss"], rel=1e-5)


def test_pause_and_resume_from_checkpoint(tmp_path):
    cfg = TrainConfig(max_steps=8, batch_size=4, learning_rate=1e-3, seed=2, save_every=0)
    seen = []

    def pause_at_3(step, total, loss, lr):
        seen.append(step)
        return "pause" if step == 3 else None

    with pytest.raises(TrainingInterrupted) as ei:
        train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "o", ckpt_dir=tmp_path / "ck", on_step=pause_at_3)
    assert ei.value.kind == "pause" and ei.value.step == 3
    assert (tmp_path / "ck" / "state.pt").exists()
    resumed = []
    summary = train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "o", ckpt_dir=tmp_path / "ck",
                         on_step=lambda s, *_: resumed.append(s))
    assert resumed == [4, 5, 6, 7, 8] and summary["steps"] == 8


def test_config_limits():
    with pytest.raises(ValueError):
        TrainConfig.from_params({"lora_r": 999}, get_settings())
    with pytest.raises(ValueError):
        TrainConfig.from_params({"learning_rate": 1.0}, get_settings())
    cfg = TrainConfig.from_params({"max_steps": 10**9, "max_seq_len": 99999}, get_settings())
    assert cfg.max_steps == get_settings().max_train_steps and cfg.max_seq_len == get_settings().max_seq_len


def test_promotion_gate():
    fam = lambda a, b: {"x": {"accuracy": a, "n": 4, "correct": 0}, "y": {"accuracy": b, "n": 4, "correct": 0}}
    parent = {"n": 8, "accuracy": 0.5, "per_family": fam(0.5, 0.5)}
    assert promotion_gate({"n": 8, "accuracy": 0.6, "per_family": fam(0.6, 0.6)}, parent)[0]
    assert not promotion_gate({"n": 8, "accuracy": 0.4, "per_family": fam(0.4, 0.4)}, parent)[0]
    ok, reasons = promotion_gate({"n": 8, "accuracy": 0.6, "per_family": fam(1.0, 0.2)}, parent)
    assert not ok and any("Rückschritt" in r for r in reasons)
    assert not promotion_gate({"n": 7, "accuracy": 1.0, "per_family": {}}, parent)[0]


def test_evaluate_items_runs(tiny_model_dir):
    from rubine.llm.engine import load_base_model, load_tokenizer
    from rubine.training.evalset import load_eval_set
    st = get_settings()
    tok, model = load_tokenizer(st), load_base_model(st, "cpu")
    items, _ = load_eval_set()
    r = evaluate_items(model, tok, items[:4], "cpu", max_new_tokens=8)
    assert r["n"] == 4 and 0.0 <= r["accuracy"] <= 1.0 and len(r["results"]) == 4


def test_full_train_job_never_auto_activates():
    with session_scope() as s:
        s.execute(delete(Example))
        D.add_synthetic(s, 40, seed=11)
    jid = jm.submit("train", {"max_steps": 4, "batch_size": 4, "learning_rate": 1e-3, "seed": 1})
    assert runner.main(jid) == 0
    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.status == "completed", job.error
        vid = job.result["version_id"]
        v = s.get(ModelVersion, vid)
        assert v.status in ("passed", "failed_eval")
        assert v.metrics["gate"]["reasons"]
        assert registry.active_version_id(s) == "base"  # never auto-activated
        assert s.query(EvalRun).filter(EvalRun.version_id.in_([vid, "base"])).count() >= 2
        # only one training at a time
        if v.status == "passed":
            registry.activate(s, vid)
            assert registry.active_version_id(s) == vid
            registry.rollback(s)
            assert registry.active_version_id(s) == "base"


def test_failed_version_cannot_be_activated():
    with session_scope() as s:
        s.merge(ModelVersion(id="rv-9999", name="kaputt", status="failed_eval", base_model="x", adapter_path=None))
        s.flush()
        with pytest.raises(registry.RegistryError):
            registry.activate(s, "rv-9999")


def test_job_limits():
    jid = jm.submit("synthetic", {"n": 1})
    with session_scope() as s:
        s.get(Job, jid).status = "paused"
        s.get(Job, jid).type = "train"
    with pytest.raises(jm.JobError):
        jm.submit("train", {})  # a paused training blocks a new one
    jm.request_stop(jid)
    with session_scope() as s:
        assert s.get(Job, jid).status == "stopped"


@pytest.mark.skipif(not os.environ.get("RUBINE_TEST_REAL_MODEL"), reason="set RUBINE_TEST_REAL_MODEL=1 (downloads/uses Qwen2.5-0.5B, ~2 min on CPU)")
def test_real_model_learns(tmp_path, monkeypatch):
    """Opt-in: LoRA on the real base model must clearly reduce the loss on verified tasks."""
    from rubine.config import Settings
    from rubine.training import curriculum as cur
    st = Settings(base_model="Qwen/Qwen2.5-0.5B-Instruct", base_model_revision="7ae557604adf67be50417f59c2c2f167def9a775",
                  data_dir=tmp_path)
    rows = [{"messages": [{"role": "user", "content": t.prompt}, {"role": "assistant", "content": t.solution}]}
            for t in cur.generate_tasks(40, "real-test")]
    cfg = TrainConfig(max_steps=20, epochs=3, batch_size=4, learning_rate=2e-4, seed=1, save_every=0)
    s = train_lora(rows=rows, cfg=cfg, out_dir=tmp_path / "o", ckpt_dir=tmp_path / "c", settings=st)
    assert s["mean_loss_last10"] < s["mean_loss_first10"] * 0.7


def test_training_actually_changes_parameters(tmp_path):
    """LoRA B matrices start at zero; after training they must be non-zero (weights really changed)."""
    from safetensors.torch import load_file
    cfg = TrainConfig(max_steps=3, batch_size=4, learning_rate=1e-3, seed=4, save_every=0)
    train_lora(rows=ROWS, cfg=cfg, out_dir=tmp_path / "o", ckpt_dir=tmp_path / "c")
    tensors = load_file(str(tmp_path / "o" / "adapter_model.safetensors"))
    b_mats = [t for k, t in tensors.items() if "lora_B" in k]
    assert b_mats and all(float(t.abs().sum()) > 0 for t in b_mats)

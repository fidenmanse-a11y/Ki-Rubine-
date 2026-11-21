"""Model version registry: versions, activation history, rollback."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Activation, ModelVersion, audit

BASE_ID = "base"
# Only these statuses may be selected in the production chat or activated.
CHAT_STATUSES = {"base", "passed"}
ACTIVATABLE_STATUSES = {"base", "passed"}


class RegistryError(ValueError):
    pass


def ensure_base_version(s: Session) -> ModelVersion:
    st = get_settings()
    v = s.get(ModelVersion, BASE_ID)
    if v is None:
        v = ModelVersion(id=BASE_ID, name="Rubine Basis", status="base", base_model=st.base_model,
                         hyperparams={"revision": st.base_model_revision, "license": st.base_model_license},
                         notes="Unverändertes Basismodell ohne LoRA-Adapter.")
        s.add(v)
        s.flush()
    if s.scalars(select(Activation).limit(1)).first() is None:
        s.add(Activation(version_id=BASE_ID, previous_version_id=None, reason="initial"))
        s.flush()
    return v


def active_version_id(s: Session) -> str:
    row = s.scalars(select(Activation).order_by(Activation.id.desc()).limit(1)).first()
    return row.version_id if row else BASE_ID


def next_version_id(s: Session) -> str:
    ids = [v for v in s.scalars(select(ModelVersion.id)) if v.startswith("rv-")]
    n = max([int(i.split("-")[1]) for i in ids] or [0]) + 1
    return f"rv-{n:04d}"


def adapter_dir(version_id: str) -> Path:
    return get_settings().models_dir / version_id / "adapter"


def activate(s: Session, version_id: str, reason: str = "activate") -> Activation:
    v = s.get(ModelVersion, version_id)
    if v is None:
        raise RegistryError("Unbekannte Modellversion")
    if v.status not in ACTIVATABLE_STATUSES:
        raise RegistryError(
            f"Version {version_id} hat Status '{v.status}'. Nur getestete Versionen (passed) können aktiviert werden.")
    if v.id != BASE_ID and not (v.adapter_path and Path(v.adapter_path).exists()):
        raise RegistryError("Adapter-Dateien fehlen – Aktivierung abgelehnt.")
    prev = active_version_id(s)
    if prev == version_id:
        raise RegistryError("Diese Version ist bereits aktiv.")
    a = Activation(version_id=version_id, previous_version_id=prev, reason=reason)
    s.add(a)
    audit(s, "model.activate", version=version_id, previous=prev, reason=reason)
    s.flush()
    return a


def rollback(s: Session) -> Activation:
    """Re-activate the version that was active before the current one."""
    history = list(s.scalars(select(Activation).order_by(Activation.id.desc())))
    if not history:
        raise RegistryError("Keine Aktivierungshistorie vorhanden.")
    current = history[0].version_id
    for a in history[1:]:
        cand = a.version_id
        if cand == current:
            continue
        v = s.get(ModelVersion, cand)
        if v and v.status in ACTIVATABLE_STATUSES:
            return activate(s, cand, reason="rollback")
    raise RegistryError("Keine frühere funktionsfähige Version gefunden.")

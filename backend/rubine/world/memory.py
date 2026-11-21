"""Agent long-term memory (memory stream) with retrieval.

Retrieval score = recency + importance + relevance, following the
Generative Agents design. Relevance is lexical (token overlap / cosine on
term counts) – no embedding model is required, which keeps the simulation
cheap on CPUs. Importance is a heuristic per memory kind (documented, not
LLM-rated) to save model calls.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import Memory

KIND_IMPORTANCE = {"observation": 2.0, "plan": 3.0, "conversation": 4.0, "task": 6.0, "reflection": 7.0}
_STOP = set("der die das und ist ein eine zu in mit auf für von den im es ich du sie er wir ihr nicht "
            "auch an als am so wie was dass hat habe bei nach über oder aber wenn noch nur".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zäöüß0-9]+", text.lower()) if len(w) > 2 and w not in _STOP]


def relevance(query: str, text: str) -> float:
    a, b = Counter(tokens(query)), Counter(tokens(text))
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a)
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def add_memory(s: Session, agent_id: str, kind: str, content: str, sim_time: int,
               importance: float | None = None) -> Memory:
    m = Memory(agent_id=agent_id, kind=kind, content=content[:1000],
               importance=importance if importance is not None else KIND_IMPORTANCE.get(kind, 3.0),
               sim_time=sim_time, last_access=sim_time)
    s.add(m)
    return m


def retrieve(s: Session, agent_id: str, query: str, now: int, k: int = 5, pool: int = 200) -> list[Memory]:
    mems = list(s.scalars(select(Memory).where(Memory.agent_id == agent_id)
                          .order_by(Memory.id.desc()).limit(pool)))
    if not mems:
        return []
    scored = []
    for m in mems:
        hours = max(0.0, (now - m.last_access) / 60.0)
        recency = 0.99 ** hours
        imp = m.importance / 10.0
        rel = relevance(query, m.content)
        scored.append((recency + imp + 1.5 * rel, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for _, m in scored[:k]]
    for m in top:
        m.last_access = now
    return top


def importance_since(s: Session, agent_id: str, since_sim: int) -> float:
    return float(s.scalar(select(func.coalesce(func.sum(Memory.importance), 0.0))
                          .where(Memory.agent_id == agent_id, Memory.sim_time > since_sim,
                                 Memory.kind != "reflection")) or 0.0)

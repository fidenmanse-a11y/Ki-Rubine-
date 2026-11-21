"""Teacher plumbing. The HTTP server is mocked here (test double); no real model is claimed."""
import httpx

from rubine.config import Settings
from rubine.training import teachers as T


def test_openai_compatible_teacher_request_format(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, timeout=None, json=None):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Antwort: 4"}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(T.httpx, "post", fake_post)
    st = Settings(teacher_openai_base_url="http://localhost:11434/v1/", teacher_openai_model="qwen2.5:7b",
                  teacher_openai_api_key="k-123")
    t = T.OpenAICompatibleTeacher(st)
    assert t.generate([{"role": "user", "content": "2+2?"}]) == "Antwort: 4"
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["json"]["model"] == "qwen2.5:7b" and seen["json"]["messages"][0]["role"] == "system"
    assert seen["headers"] == {"Authorization": "Bearer k-123"}


def test_teachers_report_unavailable_without_config():
    st = Settings(anthropic_api_key="", teacher_openai_base_url=None, teacher_local_hf_model=None)
    by = {t["name"]: t for t in T.list_teachers(st)}
    assert not by["anthropic"]["available"] and not by["openai_compatible"]["available"]
    assert by["manual_import"]["available"]

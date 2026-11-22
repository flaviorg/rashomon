import pytest

from rashomon.llm.factory import DEFAULT_ANTHROPIC_MODEL, resolve_model
from rashomon.llm.fake import ScriptedLLM
from rashomon.llm.port import LLMError
from rashomon.llm.real import build_chat_model
from rashomon.models import Plan, QuestionDrafts


def test_model_resolution_order():
    assert resolve_model("openai:x", {"RASHOMON_MODEL": "y", "ANTHROPIC_API_KEY": "k"}) == "openai:x"
    assert resolve_model(None, {"RASHOMON_MODEL": "y", "ANTHROPIC_API_KEY": "k"}) == "y"
    assert resolve_model(None, {"ANTHROPIC_API_KEY": "k"}) == DEFAULT_ANTHROPIC_MODEL
    assert resolve_model(None, {}) == "fake"


def test_fake_fallbacks_are_valid_and_count_tokens():
    llm = ScriptedLLM()
    reply = llm.structured("sys", "user", Plan)
    assert "only knows the bundled demo" in reply.value.summary and reply.tokens > 0
    assert llm.structured("s", "u", QuestionDrafts).value.questions == []
    with pytest.raises(TypeError):
        llm.structured("s", "u", dict)


def test_openrouter_without_key_is_an_llm_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMError):
        build_chat_model("openrouter:x/y")

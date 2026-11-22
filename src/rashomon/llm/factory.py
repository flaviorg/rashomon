"""Pick a model from flags and environment. No key means the scripted fake: everything stays offline."""

from __future__ import annotations

import os

from rashomon.llm.port import LLM

DEFAULT_ANTHROPIC_MODEL = "anthropic:claude-sonnet-5-5"


def resolve_model(flag: str | None = None, env: dict[str, str] | None = None) -> str:
    """``--model`` > ``RASHOMON_MODEL`` > Anthropic default if a key exists > ``fake``."""
    env = dict(os.environ) if env is None else env
    for value in (flag, env.get("RASHOMON_MODEL")):
        if value:
            return value
    if env.get("ANTHROPIC_API_KEY"):
        return DEFAULT_ANTHROPIC_MODEL
    return "fake"


def make_llm(model: str) -> LLM:
    if model == "fake":
        from rashomon.llm.demo_script import demo_llm

        return demo_llm()
    from rashomon.llm.real import LangChainLLM

    return LangChainLLM(model, temperature=0.7)

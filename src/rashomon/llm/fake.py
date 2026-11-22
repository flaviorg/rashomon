"""A deterministic, scripted stand-in for a model.

Rules are matched against the prompt text, not against call order, so the fake is stateless:
a run that is interrupted, left for a week and resumed gets the same answers, and the five
parallel ``interpret`` calls can run in any order. This is what makes the demo and the tests
reproducible offline.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from rashomon.llm.port import LLMReply, T
from rashomon.models import Plan, QuestionDrafts

SCHEMA_KEYS: dict[type, str] = {Plan: "plan", QuestionDrafts: "questions"}
Responder = dict[str, Any] | Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class Rule:
    schema: str  # "plan" | "questions"
    respond: Responder
    when: tuple[str, ...] = ()
    unless: tuple[str, ...] = ()

    def matches(self, schema: str, prompt: str) -> bool:
        return (
            schema == self.schema and all(s in prompt for s in self.when) and not any(s in prompt for s in self.unless)
        )


@dataclass
class ScriptedLLM:
    rules: list[Rule] = field(default_factory=list)
    name: str = "fake"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def structured(self, system: str, user: str, schema: type[T]) -> LLMReply[T]:
        key = SCHEMA_KEYS.get(schema)
        if key is None:
            raise TypeError(f"ScriptedLLM has no fallback for {schema.__name__}")
        self.calls.append((key, user))
        rule = next((r for r in self.rules if r.matches(key, user)), None)
        if rule is None:
            payload = self._fallback(key)
        else:
            payload = rule.respond(user) if callable(rule.respond) else rule.respond
        value = schema.model_validate(payload)
        return LLMReply(value, self._tokens(system, user, value))

    @staticmethod
    def _tokens(system: str, user: str, value: BaseModel) -> int:
        # ~4 chars per token: a rough but honest stand-in so token totals mean something offline
        return (len(system) + len(user) + len(json.dumps(value.model_dump()))) // 4

    @staticmethod
    def _fallback(key: str) -> dict[str, Any]:
        if key == "plan":
            return {
                "summary": (
                    "The scripted fake model only knows the bundled demo ticket. "
                    "Set ANTHROPIC_API_KEY or RASHOMON_MODEL to use a real model."
                ),
                "size": "M",
            }
        return {"questions": []}

"""The one interface the graph depends on: ask for a structured answer, get it plus token spend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model failed or returned something that does not fit the schema."""


@dataclass
class LLMReply(Generic[T]):
    value: T
    tokens: int


class LLM(Protocol):
    name: str

    def structured(self, system: str, user: str, schema: type[T]) -> LLMReply[T]: ...

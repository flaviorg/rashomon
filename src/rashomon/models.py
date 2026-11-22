"""Typed shapes the model fills in. Everything downstream of these is plain code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Size = Literal["XS", "S", "M", "L", "XL"]
SIZES: tuple[str, ...] = ("XS", "S", "M", "L", "XL")


class FileTouch(BaseModel):
    path: str = Field(description="Repo-relative path. Use a path from the context pack, or mark change='new'.")
    change: Literal["modify", "new", "delete"] = "modify"
    why: str = ""


class Behaviour(BaseModel):
    """One observable behaviour, as Given / When / Then."""

    given: str
    when: str
    then: str


class Assumption(BaseModel):
    """A judgement call on a point the ticket leaves open."""

    topic: str = Field(description="Short noun phrase naming the open point, e.g. 'export scope'.")
    choice: str = Field(description="What this plan assumes, e.g. 'the filtered view'.")


class Plan(BaseModel):
    """One interpretation of the ticket, concrete enough to diff against the others."""

    summary: str = Field(description="One or two sentences: what you would build.")
    files: list[FileTouch] = Field(default_factory=list)
    api_changes: list[str] = Field(default_factory=list, description="Routes, signatures or payloads added or changed.")
    schema_changes: list[str] = Field(default_factory=list, description="Tables, columns, migrations. Empty if none.")
    behaviours: list[Behaviour] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    size: Size = "M"


class QuestionDraft(BaseModel):
    divergence_id: str = Field(description="Copy the id exactly as given.")
    question: str = Field(description="One plain question a product owner can answer.")
    options: list[str] = Field(description="Answer options. Copy them from the allowed values; do not invent new ones.")


class QuestionDrafts(BaseModel):
    questions: list[QuestionDraft] = Field(default_factory=list)

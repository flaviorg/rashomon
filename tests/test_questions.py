import pytest
from pydantic import ValidationError

from rashomon import questions
from rashomon.diff import analyse
from rashomon.llm.fake import Rule, ScriptedLLM
from rashomon.llm.port import LLMError
from tests.helpers import plan, records


def _analysis():
    return analyse(
        records(
            plan({"export scope": "filtered"}, schema=["add table jobs"]),
            plan({"export scope": "filtered"}),
            plan({"export scope": "all rows"}),
            plan({"export scope": "all rows"}),
            plan({"export scope": "all rows"}),
        )
    )


def test_select_orders_by_impact_and_skips_settled():
    sel = questions.select(_analysis(), {})
    assert [d["id"] for d in sel] == ["assumption:export-scope", "schema:changes"]
    settled = {"assumption:export-scope": {"dimension": "assumption", "topic": "export scope", "value": "filtered"}}
    assert [d["id"] for d in questions.select(_analysis(), settled)] == ["schema:changes"]


def test_invented_options_are_dropped_and_real_ones_restored():
    sel = questions.select(_analysis(), {})
    drafts = [
        {
            "divergence_id": "assumption:export-scope",
            "question": "Which rows?",
            "options": ["Filtered", "Let the user pick"],
        },
        {"divergence_id": "made-up", "question": "?", "options": []},
    ]
    qs, notes = questions.validate(drafts, sel)
    assert [o["value"] for o in qs[0]["options"]] == ["filtered", "all rows"]
    assert qs[0]["question"] == "Which rows?"
    assert {n["code"] for n in notes} == {"invented_option", "missing_option", "unknown_divergence"}
    assert qs[1]["question"] == "Which schema changes should this ticket make?"  # template fallback


def test_recommendation_prefers_precedent_over_majority():
    sel = questions.select(_analysis(), {})
    qs, _ = questions.validate([], sel)
    assert qs[0]["recommended"] == "all rows" and qs[0]["recommended_because"] == "majority (C,D,E)"
    precedent = [{"dimension": "assumption", "topic": "export scope", "value": "filtered", "ticket": "GH-9"}]
    qs, _ = questions.validate([], sel, precedent)
    assert qs[0]["recommended"] == "filtered" and qs[0]["recommended_because"] == "decided on GH-9"


def test_model_failure_falls_back_to_templates():
    class Broken:
        name = "broken"

        def structured(self, *a):
            raise LLMError("boom")

    qs, notes, used = questions.draft(Broken(), {}, questions.select(_analysis(), {}), [])
    assert len(qs) == 2 and notes[0]["code"] == "llm_error" and used == 0


def test_draft_uses_the_model_phrasing():
    llm = ScriptedLLM(
        [
            Rule(
                "questions",
                {"questions": [{"divergence_id": "assumption:export-scope", "question": "Rows?", "options": []}]},
            )
        ]
    )
    qs, _, _ = questions.draft(llm, {}, questions.select(_analysis(), {}), [])
    assert qs[0]["question"] == "Rows?"


def test_answer_schema_only_accepts_offered_values():
    qs, _ = questions.validate([], questions.select(_analysis(), {}))
    schema = questions.answer_schema(qs)
    ok = schema.model_validate({"q1": "all rows", "q2": "none"})
    assert ok.model_dump() == {"q1": "all rows", "q2": "none"}
    with pytest.raises(ValidationError):
        schema.model_validate({"q1": "something else", "q2": "none"})
    with pytest.raises(ValidationError):
        schema.model_validate({"q1": "all rows"})

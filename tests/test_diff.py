from rashomon.diff import analyse, impact, support
from rashomon.lenses import letters
from tests.helpers import plan, records


def _row(analysis, row_id):
    return next(d for d in analysis["divergences"] if d["id"] == row_id)


def test_choice_divergence_groups_lenses_by_value():
    a = analyse(
        records(
            plan({"export scope": "the filtered view"}),
            plan({"export scope": "the filtered view"}),
            plan({"export scope": "all rows"}),
            plan({"scope of the export": "all rows"}),  # paraphrased topic clusters with the others
            plan({"export scope": "All rows"}),
        )
    )
    row = _row(a, "assumption:export-scope")
    split = [(letters(g["lenses"]), g["value"]) for g in row["groups"]]
    assert split == [("C,D,E", "all rows"), ("A,B", "the filtered view")]
    assert row["askable"] and row["impact"] == 2.4


def test_unanimous_assumption_is_agreed_not_divergent():
    a = analyse(records(*[plan({"currency": "USD only"}) for _ in range(5)]))
    assert not [d for d in a["divergences"] if d["dimension"] == "assumption"]
    assert a["agreed"][0]["topic"] == "currency"


def test_silent_lens_is_reported():
    a = analyse(records(plan({"x scope": "a"}), plan({"x scope": "b"}), plan(), plan(), plan()))
    row = _row(a, "assumption:x-scope")
    assert row["silent"] == ["defensive", "performance", "ux"]


def test_set_dimension_treats_none_as_a_value():
    a = analyse(records(plan(), plan(), plan(), plan(schema=["add table export_jobs"]), plan()))
    row = _row(a, "schema:changes")
    assert [(letters(g["lenses"]), g["value"]) for g in row["groups"]] == [
        ("A,B,C,E", "none"),
        ("D", "add table export_jobs"),
    ]
    assert row["groups"][1]["items"] == ["add table export_jobs"]


def test_api_routes_that_differ_by_one_token_stay_apart():
    a = analyse(records(plan(api=["GET /invoices/export.csv"]), plan(api=["GET /invoices?format=csv"])))
    assert len(_row(a, "api:changes")["groups"]) == 2


def test_presence_rows_are_not_askable():
    a = analyse(records(plan(files=["a.py", "b.py"]), plan(files=["a.py"]), plan(files=["a.py"])))
    row = _row(a, "files:b-py")
    assert not row["askable"] and row["kind"] == "presence"
    assert not any(d["id"] == "files:a-py" for d in a["divergences"])


def test_impact_is_zero_for_unanimity_and_max_for_even_split():
    assert impact("assumption", [{"lenses": ["a"] * 5}]) == 0.0
    assert impact("assumption", [{"lenses": ["a", "b"]}, {"lenses": ["c", "d"]}]) == 3.0
    assert impact("schema", [{"lenses": ["a"] * 4}, {"lenses": ["e"]}]) == 0.8


def test_divergences_sorted_by_impact_then_askable():
    a = analyse(
        records(
            plan({"t": "x"}, files=["f.py"]),
            plan({"t": "x"}),
            plan({"t": "y"}),
            plan({"t": "y"}),
            plan({"t": "y"}),
        )
    )
    assert a["divergences"][0]["id"] == "assumption:t"


def test_support_counts_lenses_per_item():
    rows = support(
        records(plan(out_of_scope=["PDF export"]), plan(out_of_scope=["PDF export", "xlsx"])), "out_of_scope"
    )
    assert rows == [("PDF export", ["literal-pm", "minimal-diff"]), ("xlsx", ["minimal-diff"])]

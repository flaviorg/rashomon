from rashomon.backtest import backtest, load_dataset, match_change
from rashomon.graph import Deps
from rashomon.llm.demo_script import demo_llm
from tests.conftest import EXAMPLE, REPO

DIVS = [
    {
        "id": "assumption:export-scope",
        "topic": "export scope",
        "groups": [{"value": "all rows"}, {"value": "the filtered view"}],
    },
    {"id": "assumption:amount-format", "topic": "amount format", "groups": [{"value": "integer cents"}]},
]


def test_match_change_by_topic_or_value():
    assert match_change("Amounts must show dollars", DIVS)[0] == "assumption:amount-format"
    assert match_change("only the filtered view please", DIVS)[0] == "assumption:export-scope"
    assert match_change("add dark mode", DIVS)[0] is None


def test_bundled_backtest_numbers():
    cases = load_dataset(REPO / "examples" / "backtest" / "closed_issues.jsonl")
    report = backtest(cases, EXAMPLE, Deps(llm=demo_llm()), "invoice_app")
    first, second = report.cases
    assert [c["matched"] for c in first.changes] == ["assumption:export-scope", "assumption:amount-format", None]
    assert second.predicted == [] and second.hits == 0
    assert report.change_recall == 0.5
    assert round(report.question_precision, 3) == 0.667

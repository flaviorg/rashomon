import json

from typer.testing import CliRunner

from rashomon.cli import app, parse_answers
from tests.conftest import EXAMPLE, TICKET_FILE

runner = CliRunner()


def _run(*args):
    return runner.invoke(app, list(args), catch_exceptions=False)


def test_demo_runs_offline_and_writes_a_spec(tmp_path):
    res = _run("demo", "--state-dir", str(tmp_path))
    assert res.exit_code == 0, res.output
    assert "converged after 3 round(s)" in res.output
    specs = list((tmp_path / "runs").glob("*/spec.md"))
    assert len(specs) == 1 and "# Spec: Export invoices to CSV" in specs[0].read_text()


def test_demo_json(tmp_path):
    res = runner.invoke(app, ["demo", "--json", "--state-dir", str(tmp_path)])
    data = json.loads(res.stdout)
    assert data["outcome"] == "converged" and data["convergence"] == [0.428, 0.716, 0.876]


def test_run_pauses_then_answers_arrive_later(tmp_path):
    state = str(tmp_path / "st")
    spec = tmp_path / "spec.md"
    res = _run("run", str(TICKET_FILE), "--repo", str(EXAMPLE), "--model", "fake", "--no-input",
               "--state-dir", state, "--thread", "t1", "--json", "--out", str(spec))  # fmt: skip
    assert res.exit_code == 3
    assert json.loads(res.stdout)["pending"]["round"] == 1

    res = _run("answer", "t1", "q1=2", "q2=the filtered view", "q3=1", "--state-dir", state, "--json")
    assert res.exit_code == 3, res.output
    assert [q["topic"] for q in json.loads(res.stdout)["pending"]["questions"]] == ["delivery method", "schema changes"]

    res = _run("answer", "t1", "q1=1", "q2=none", "--state-dir", state, "--json")
    assert res.exit_code == 0, res.output
    out = json.loads(res.stdout)
    assert out["outcome"] == "converged"
    assert {s["topic"]: s["value"] for s in out["settled"]}["amount format"] == "formatted currency ($1,234.50)"


def test_answer_rejects_values_no_plan_proposed(tmp_path):
    state = str(tmp_path)
    _run(
        "run",
        str(TICKET_FILE),
        "--repo",
        str(EXAMPLE),
        "--model",
        "fake",
        "--no-input",
        "--state-dir",
        state,
        "--thread",
        "t2",
    )
    res = _run("answer", "t2", "q1=Let the user choose per export", "q2=1", "q3=1", "--state-dir", state)
    assert res.exit_code == 2 and "not one of the options" in res.output
    res = _run("answer", "t2", "q1=1", "--state-dir", state)
    assert res.exit_code == 2 and "missing answers" in res.output
    assert _run("answer", "nope", "q1=1", "--state-dir", state).exit_code == 2


def test_speckit_clarifications_and_out_apply_when_answers_arrive_later(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Feature: export\n\n## User Scenarios\n\nstuff\n")
    out = tmp_path / "out" / "rashomon-spec.md"
    state = str(tmp_path / "st")
    _run("run", str(TICKET_FILE), "--repo", str(EXAMPLE), "--model", "fake", "--no-input", "--state-dir", state,
         "--thread", "sk", "--speckit", str(spec), "--out", str(out))  # fmt: skip
    _run("answer", "sk", "q1=1", "q2=1", "q3=1", "--state-dir", state)
    assert "## Clarifications" not in spec.read_text()
    res = _run("answer", "sk", "q1=1", "q2=1", "--state-dir", state)
    assert res.exit_code == 0
    text = spec.read_text()
    assert text.startswith("# Feature: export") and "## Clarifications\n\n### Session " in text
    assert "- Q: How should amounts appear in the CSV? → A: integer cents" in text
    assert text.count("- Q: ") == 5
    assert out.read_text().startswith("# Spec: Export invoices to CSV")


def test_parse_answers_numbers_and_values():
    pending = {
        "kind": "questions",
        "questions": [{"id": "q1", "options": [{"value": "a"}, {"value": "b"}]}],
    }
    assert parse_answers(pending, ["q1=2"]) == {"q1": "b"}
    assert parse_answers(pending, ["q1=a"]) == {"q1": "a"}
    assert parse_answers({"kind": "approve_post"}, ["approve=yes"]) == {"approve": True}


def test_graph_and_version_commands():
    assert "diff_plans" in _run("graph").output
    assert _run("version").output.strip() == "0.1.1"


def test_backtest_on_bundled_sample():
    res = runner.invoke(app, ["backtest", "--json"])
    data = json.loads(res.stdout)
    assert data["cases"] == 2 and data["changes"] == 4
    assert data["change_recall"] == 0.5 and data["question_precision"] == 0.667


def test_decisions_listing(tmp_path):
    _run("demo", "--state-dir", str(tmp_path))
    res = _run("decisions", "--demo", "--state-dir", str(tmp_path))
    assert "export scope = the filtered view" in res.output


def test_missing_ticket_file_is_an_error(tmp_path):
    res = _run("run", "nope.md", "--state-dir", str(tmp_path))
    assert res.exit_code == 2 and "neither a GitHub reference" in res.output

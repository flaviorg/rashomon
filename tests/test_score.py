from rashomon.diff import analyse
from rashomon.score import convergence
from tests.helpers import plan, records


def test_identical_plans_converge_fully():
    p = plan({"scope": "all"}, api=["GET /x"], files=["a.py"], behaviours=[("g", "w", "t")], size="M")
    assert convergence(analyse(records(*[p] * 5)))["score"] == 1.0


def test_disagreement_lowers_the_score_by_dimension():
    a = analyse(
        records(
            plan({"scope": "a"}), plan({"scope": "a"}), plan({"scope": "b"}), plan({"scope": "b"}), plan({"scope": "b"})
        )
    )
    conv = convergence(a)
    assert conv["by_dimension"]["assumption"] == 0.4  # 4 of 10 pairs agree
    assert conv["by_dimension"]["api"] == 1.0
    assert conv["score"] < 1.0


def test_size_is_ordinal():
    near = convergence(analyse(records(plan(size="S"), plan(size="M"))))["by_dimension"]["size"]
    far = convergence(analyse(records(plan(size="XS"), plan(size="XL"))))["by_dimension"]["size"]
    assert near == 0.75 and far == 0.0

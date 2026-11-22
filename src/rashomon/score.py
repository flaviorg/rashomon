"""Convergence is a number code computes, never something the model declares.

For every dimension, take the mean pairwise Jaccard similarity of the plans' signatures
(cluster ids from ``diff.analyse``), then a weighted mean across dimensions. Size is ordinal:
XS vs XL scores 0, neighbours score 0.75.
"""

from __future__ import annotations

from itertools import combinations

from rashomon.diff import WEIGHTS
from rashomon.models import SIZES

DEFAULT_THRESHOLD = 0.8


def _pair_similarity(dimension: str, a: list, b: list) -> float:
    if dimension == "size":
        ia = SIZES.index(a[0]) if a and a[0] in SIZES else 2
        ib = SIZES.index(b[0]) if b and b[0] in SIZES else 2
        return 1 - abs(ia - ib) / (len(SIZES) - 1)
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def convergence(analysis: dict) -> dict:
    lenses = analysis["lenses"]
    by_dimension: dict[str, float] = {}
    for dimension in WEIGHTS:
        sigs = analysis["signatures"].get(dimension, {})
        pairs = list(combinations(lenses, 2))
        if not pairs:
            by_dimension[dimension] = 1.0
            continue
        sims = [_pair_similarity(dimension, sigs.get(x, []), sigs.get(y, [])) for x, y in pairs]
        by_dimension[dimension] = round(sum(sims) / len(sims), 3)
    total = sum(WEIGHTS.values())
    score = round(sum(WEIGHTS[d] * by_dimension[d] for d in WEIGHTS) / total, 3)
    return {"score": score, "by_dimension": by_dimension}

"""Deterministic text normalization shared by grounding, diffing and backtesting.

No embeddings and no model: lowercase, split identifiers, drop stopwords, crude stemming,
then compare token sets. Crude on purpose: it is reproducible and easy to reason about.
"""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a an the and or of to in on for with by from at as is are be been being it its this that these those
    we you they he she i our your their them should would could can will shall must may might do does did
    not no so if then than when while into onto out up down over under about via per each every any all
    please also just only some such which who whom whose what where how why there here have has had
    want wants need needs new add adds added make makes use uses using""".split()  # noqa: SIM905
)
# words that carry meaning in a requirement even though they look like filler
KEEP = frozenset({"all", "only", "no", "not", "new", "none"})

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def stem(word: str) -> str:
    w = word.lower()
    if len(w) <= 3 or w.endswith(("ss", "us", "is")):
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return w[:-2]
    for suffix in ("ing", "ed", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            if suffix != "s" and len(w) >= 4 and w[-1] == w[-2] and w[-1] in "bdgmnprt":
                w = w[:-1]  # formatted -> format, mapped -> map
            return w
    return w


def split_identifier(name: str) -> list[str]:
    """``InvoiceTable`` / ``invoice_query`` / ``/invoices/{id}`` -> word parts."""
    parts: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", name):
        if chunk:
            parts.extend(p for p in _CAMEL.sub(" ", chunk).split() if p)
    return parts


def tokens(text: str, keep_meaningful: bool = True) -> frozenset[str]:
    out: set[str] = set()
    for raw in _TOKEN.findall(text or ""):
        for part in split_identifier(raw):
            low = part.lower()
            if low in STOPWORDS and not (keep_meaningful and low in KEEP):
                continue
            if len(low) < 2:
                continue
            out.add(stem(low))
    return frozenset(out)


def jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def containment(needle: frozenset[str], haystack: frozenset[str]) -> float:
    """Share of ``needle`` tokens found in ``haystack``."""
    if not needle:
        return 0.0
    return len(needle & haystack) / len(needle)


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "item"


def cluster(items: list[str], threshold: float) -> list[int]:
    """Greedy single-pass clustering by token Jaccard. Returns a cluster index per item.

    Order matters (first item of a cluster is its representative) and the input order is
    always lens order, so the result is deterministic.
    """
    reps: list[frozenset[str]] = []
    exact: list[str] = []
    out: list[int] = []
    for item in items:
        tok = tokens(item)
        norm = " ".join((item or "").lower().split())
        idx = next(
            (
                i
                for i, (r, e) in enumerate(zip(reps, exact, strict=True))
                if e == norm or (tok and r and jaccard(tok, r) >= threshold)
            ),
            None,
        )
        if idx is None:
            reps.append(tok)
            exact.append(norm)
            idx = len(reps) - 1
        out.append(idx)
    return out

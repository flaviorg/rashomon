"""Where do the five plans disagree? Pure code, no model.

The output is a divergence matrix: one row per open point, each row a list of groups
("A,B: the filtered view" / "C,D,E: all rows"). Rows come from three places:

* ``choice``: assumptions whose topics cluster together but whose choices do not.
* ``set``: API and schema changes, compared as whole sets per plan ("none" is a value).
* ``presence``: files, behaviours and out-of-scope items that some plans include and others do not.

Only ``choice`` and ``set`` rows can become questions; presence rows feed the score and the spec.
"""

from __future__ import annotations

from collections import OrderedDict

from rashomon.lenses import LENSES
from rashomon.text import cluster, slug

WEIGHTS: dict[str, float] = {
    "assumption": 3.0,
    "api": 2.0,
    "schema": 2.0,
    "files": 1.5,
    "behaviours": 1.0,
    "out_of_scope": 0.5,
    "size": 1.0,
}
ASKABLE = frozenset({"assumption", "api", "schema"})
TOPIC_THRESHOLD = 0.5
VALUE_THRESHOLD = 0.6
ITEM_THRESHOLD = {
    "api": 0.85,
    "schema": 0.6,
    "files": 1.01,
    "behaviours": 0.6,
    "out_of_scope": 0.6,
}  # paths match exactly
SET_LABELS = {"api": "API changes", "schema": "schema changes"}
PRESENCE_LABELS = {"files": "file", "behaviours": "behaviour", "out_of_scope": "out of scope"}


def impact(dimension: str, groups: list[dict]) -> float:
    """Weight of the dimension x how evenly the stated plans split (0 for unanimity, 1 for an even split)."""
    stated = sum(len(g["lenses"]) for g in groups)
    if stated == 0 or len(groups) < 2:
        return 0.0
    largest = max(len(g["lenses"]) for g in groups)
    balance = min(1.0, 2 * (stated - largest) / stated)
    return round(WEIGHTS[dimension] * balance, 2)


def _order_groups(groups: list[dict]) -> list[dict]:
    return sorted(groups, key=lambda g: (-len(g["lenses"]), g["first"]))


def behaviour_text(b: dict) -> str:
    return f"Given {b['given']}, when {b['when']}, then {b['then']}"


def _items(plan: dict, dimension: str) -> list[str]:
    if dimension == "api":
        return list(plan.get("api_changes", []))
    if dimension == "schema":
        return list(plan.get("schema_changes", []))
    if dimension == "files":
        return [f["path"] for f in plan.get("files", [])]
    if dimension == "behaviours":
        return [behaviour_text(b) for b in plan.get("behaviours", [])]
    if dimension == "out_of_scope":
        return list(plan.get("out_of_scope", []))
    raise ValueError(dimension)


def _assumption_rows(records: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    flat = [(r["lens"], a["topic"], a["choice"]) for r in records for a in r["plan"]["assumptions"]]
    topic_ids = cluster([t for _, t, _ in flat], TOPIC_THRESHOLD)
    topics: OrderedDict[int, dict] = OrderedDict()
    for (lens, topic, choice), tid in zip(flat, topic_ids, strict=True):
        entry = topics.setdefault(tid, {"label": topic, "choices": OrderedDict()})
        entry["choices"].setdefault(lens, choice)  # first assumption per lens and topic wins
    rows: list[dict] = []
    signatures: dict[str, list[str]] = {r["lens"]: [] for r in records}
    for tid, entry in topics.items():
        lenses = list(entry["choices"])
        choice_ids = cluster([entry["choices"][lens] for lens in lenses], VALUE_THRESHOLD)
        groups: OrderedDict[int, dict] = OrderedDict()
        for i, (lens, cid) in enumerate(zip(lenses, choice_ids, strict=True)):
            g = groups.setdefault(cid, {"value": entry["choices"][lens], "lenses": [], "first": i})
            g["lenses"].append(lens)
            signatures[lens].append(f"t{tid}=c{cid}")
        ordered = _order_groups(list(groups.values()))
        rows.append(
            {
                "id": f"assumption:{slug(entry['label'])}",
                "dimension": "assumption",
                "kind": "choice",
                "topic": entry["label"],
                "groups": [{"value": g["value"], "lenses": g["lenses"]} for g in ordered],
                "silent": [r["lens"] for r in records if r["lens"] not in entry["choices"]],
            }
        )
    return rows, signatures


def _item_clusters(records: list[dict], dimension: str) -> tuple[list[str], dict[str, set[int]]]:
    flat = [(r["lens"], item) for r in records for item in _items(r["plan"], dimension)]
    ids = cluster([item for _, item in flat], ITEM_THRESHOLD[dimension])
    labels: dict[int, str] = {}
    per_lens: dict[str, set[int]] = {r["lens"]: set() for r in records}
    for (lens, item), cid in zip(flat, ids, strict=True):
        labels.setdefault(cid, item)
        per_lens[lens].add(cid)
    return [labels[i] for i in range(len(labels))], per_lens


def _set_row(records: list[dict], dimension: str, labels: list[str], per_lens: dict[str, set[int]]) -> dict:
    groups: OrderedDict[frozenset[int], dict] = OrderedDict()
    for i, r in enumerate(records):
        key = frozenset(per_lens[r["lens"]])
        value = "; ".join(labels[c] for c in sorted(key)) or "none"
        g = groups.setdefault(
            key, {"value": value, "lenses": [], "first": i, "items": [labels[c] for c in sorted(key)]}
        )
        g["lenses"].append(r["lens"])
    ordered = _order_groups(list(groups.values()))
    return {
        "id": f"{dimension}:changes",
        "dimension": dimension,
        "kind": "set",
        "topic": SET_LABELS[dimension],
        "groups": [{"value": g["value"], "lenses": g["lenses"], "items": g["items"]} for g in ordered],
        "silent": [],
    }


def _presence_rows(records: list[dict], dimension: str, labels: list[str], per_lens: dict[str, set[int]]) -> list[dict]:
    rows = []
    all_lenses = [r["lens"] for r in records]
    for cid, label in enumerate(labels):
        have = [lens for lens in all_lenses if cid in per_lens[lens]]
        if len(have) == len(all_lenses):
            continue
        lack = [lens for lens in all_lenses if lens not in have]
        groups = _order_groups(
            [
                {
                    "value": f"includes {label}" if dimension != "out_of_scope" else f"rules out {label}",
                    "lenses": have,
                    "first": 0,
                },
                {"value": "leaves it out", "lenses": lack, "first": 1},
            ]
        )
        rows.append(
            {
                "id": f"{dimension}:{slug(label)}",
                "dimension": dimension,
                "kind": "presence",
                "topic": f"{PRESENCE_LABELS[dimension]}: {label}",
                "groups": [{"value": g["value"], "lenses": g["lenses"]} for g in groups],
                "silent": [],
            }
        )
    return rows


def analyse(records: list[dict]) -> dict:
    """``records``: [{"lens": id, "plan": guarded plan dict}] for one round, any order."""
    order = {lens.id: i for i, lens in enumerate(LENSES)}
    records = sorted(records, key=lambda r: order.get(r["lens"], 99))
    rows, assumption_sigs = _assumption_rows(records)
    signatures: dict[str, dict[str, list]] = {"assumption": assumption_sigs}
    for dimension in ("api", "schema"):
        labels, per_lens = _item_clusters(records, dimension)
        rows.append(_set_row(records, dimension, labels, per_lens))
        signatures[dimension] = {k: sorted(v) for k, v in per_lens.items()}
    for dimension in ("files", "behaviours", "out_of_scope"):
        labels, per_lens = _item_clusters(records, dimension)
        rows.extend(_presence_rows(records, dimension, labels, per_lens))
        signatures[dimension] = {k: sorted(v) for k, v in per_lens.items()}
    signatures["size"] = {r["lens"]: [r["plan"]["size"]] for r in records}
    for row in rows:
        row["impact"] = impact(row["dimension"], row["groups"])
        row["askable"] = row["dimension"] in ASKABLE
    divergences = sorted(
        (r for r in rows if len(r["groups"]) >= 2), key=lambda r: (-r["impact"], 0 if r["askable"] else 1, r["id"])
    )
    agreed = [r for r in rows if len(r["groups"]) == 1 and r["kind"] != "presence"]
    return {
        "lenses": [r["lens"] for r in records],
        "divergences": divergences,
        "agreed": agreed,
        "signatures": signatures,
    }


def support(records: list[dict], dimension: str) -> list[tuple[str, list[str]]]:
    """Every distinct item in ``dimension`` with the lenses that proposed it, most supported first."""
    order = {lens.id: i for i, lens in enumerate(LENSES)}
    records = sorted(records, key=lambda r: order.get(r["lens"], 99))
    labels, per_lens = _item_clusters(records, dimension)
    rows = [(label, [r["lens"] for r in records if cid in per_lens[r["lens"]]]) for cid, label in enumerate(labels)]
    return sorted(rows, key=lambda x: -len(x[1]))


def lens_value(divergence: dict, lens_id: str) -> str | None:
    for g in divergence["groups"]:
        if lens_id in g["lenses"]:
            return g["value"]
    return None

from typing import Any

import pytest

from spotcheck import pick, score


def judged(rid: str) -> dict[str, Any]:
    return {"id": rid, "judge": {"faithful": True, "relevant": True, "correct": True, "reason": ""}}


def test_pick_is_deterministic_and_only_judged_items() -> None:
    records = [judged(f"q{n:03d}") for n in range(40)] + [{"id": "r1", "refused": True}]
    a, b = pick(records, "run-1"), pick(records, "run-1")
    assert [r["id"] for r in a] == [r["id"] for r in b] and len(a) == 20
    assert all(r.get("judge") for r in a)
    assert [r["id"] for r in pick(records, "run-2")] != [r["id"] for r in a]


def sheet_item(rid: str, judge: tuple[bool, bool, bool], human: tuple[Any, Any, Any]) -> dict[str, Any]:
    keys = ("faithful", "relevant", "correct")
    return {
        "id": rid,
        "judge": dict(zip(keys, judge, strict=True)),
        "human": dict(zip(keys, human, strict=True)),
    }


def test_score_counts_disagreements_per_dimension() -> None:
    items = [
        sheet_item("a", (True, True, True), (True, True, True)),
        sheet_item("b", (True, True, False), (False, True, False)),
    ]
    out = score(items)
    assert out["faithful"] == {"agreement": 0.5, "disagreements": ["b"]}
    assert out["correct"]["agreement"] == 1.0
    assert out["overall_disagreement_rate"] == pytest.approx(1 / 6, abs=1e-4)


def test_score_refuses_unlabelled_sheets() -> None:
    with pytest.raises(SystemExit, match="unlabelled"):
        score([sheet_item("a", (True, True, True), (True, None, True))])

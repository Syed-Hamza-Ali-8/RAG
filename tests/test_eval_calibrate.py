from pathlib import Path
from typing import Any

from calibrate_judge import PASS_RATES, caught, check_item, load, summarise

CTX = {
    "a#0": ("Doc A", "Annual leave is 22 days."),
    "b#0": ("Doc B", "Sick leave is 10 days."),
}


def item(
    category: str, answer: str, check_text: str, cited: str, caught_if: dict[str, bool]
) -> dict[str, Any]:
    return {
        "id": "c",
        "category": category,
        "answer": answer,
        "check_text": check_text,
        "cited_label": cited,
        "context_gids": ["a#0", "b#0"],
        "caught_if": caught_if,
    }


def test_construction_rules() -> None:
    assert (
        check_item(item("fabrication", "It is 30 days. [S1]", "30 days", "S1", {"faithful": False}), CTX)
        == []
    )
    assert check_item(item("fabrication", "It is 22 days. [S1]", "22 days", "S1", {"faithful": False}), CTX)
    assert check_item(item("good", "22 days. [S1]", "22 days", "S1", {}), CTX) == []
    assert check_item(item("good", "22 days. [S2]", "22 days", "S2", {}), CTX)
    assert check_item(item("bad_citation", "22 days. [S2]", "22 days", "S2", {"faithful": False}), CTX) == []
    assert check_item(item("bad_citation", "22 days. [S1]", "22 days", "S1", {"faithful": False}), CTX)


def test_caught_and_summary() -> None:
    fab = {"caught_if": {"faithful": False}}
    assert caught(fab, {"faithful": False, "relevant": True, "correct": False})
    assert not caught(fab, {"faithful": True, "relevant": True, "correct": False})

    def results(cat: str, hits: int) -> list[dict[str, Any]]:
        return [
            {"id": f"{cat}{n}", "category": cat, "verdict": {}, "caught": n < hits, "full_match": False}
            for n in range(10)
        ]

    passing = (
        results("fabrication", 8)
        + results("wrong_question", 8)
        + results("bad_citation", 8)
        + results("good", 9)
    )
    s = summarise(passing)
    assert s["fabrication"]["rate"] == 0.8 and s["fabrication"]["misses"] == ["fabrication8", "fabrication9"]
    assert s["fit"] is True
    assert PASS_RATES == {"fabrication": 0.8, "wrong_question": 0.8, "bad_citation": 0.8, "good": 0.9}
    # Any one category below its bar makes the judge unfit, including false negatives on good answers.
    assert (
        summarise(
            results("fabrication", 8)
            + results("wrong_question", 8)
            + results("bad_citation", 7)
            + results("good", 9)
        )["fit"]
        is False
    )
    assert (
        summarise(
            results("fabrication", 8)
            + results("wrong_question", 8)
            + results("bad_citation", 8)
            + results("good", 8)
        )["fit"]
        is False
    )


def test_committed_v2_set_has_ten_per_category_and_keeps_v1_items() -> None:
    items = load()
    assert len(items) == 40
    cats = ("fabrication", "wrong_question", "bad_citation", "good")
    assert {c: sum(i["category"] == c for i in items) for c in cats} == dict.fromkeys(cats, 10)
    v1 = {i["id"]: i for i in load(Path("eval/judge_calibration.jsonl"))}
    for item in items[:20]:
        assert (item["answer"], item["context_gids"]) == (
            v1[item["id"]]["answer"],
            v1[item["id"]]["context_gids"],
        )
    assert all("citations_supported" in i["expected"] for i in items)
    assert all(
        i["caught_if"] == {"citations_supported": False} for i in items if i["category"] == "bad_citation"
    )

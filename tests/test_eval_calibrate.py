from typing import Any

from calibrate_judge import FABRICATION_PASS_RATE, caught, check_item, load, summarise

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
    results = [
        {"id": f"f{n}", "category": "fabrication", "verdict": {}, "caught": n < 4, "full_match": False}
        for n in range(5)
    ]
    s = summarise(results)
    assert s["fabrication"] == {"n": 5, "caught": 4, "rate": 0.8, "full_verdict_match": 0, "misses": ["f4"]}
    assert s["fit"] is True and FABRICATION_PASS_RATE == 0.8
    results[3]["caught"] = False
    assert summarise(results)["fit"] is False


def test_committed_set_has_five_per_category() -> None:
    items = load()
    assert len(items) == 20
    assert {
        c: sum(i["category"] == c for i in items)
        for c in ("fabrication", "wrong_question", "bad_citation", "good")
    } == {
        "fabrication": 5,
        "wrong_question": 5,
        "bad_citation": 5,
        "good": 5,
    }

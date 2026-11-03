import math

import pytest

from metrics import all_hops_at_k, hop_ranks, ndcg_at_k, recall_at_k, reciprocal_rank

RANKED = ["a#0", "b#1", "c#0", "d#2", "e#0", "f#0", "g#0", "h#0", "i#0", "j#0"]


def test_hop_ranks_takes_best_ranked_chunk_per_hop() -> None:
    # A fact present in two chunks: either satisfies the hop; the better rank counts.
    assert hop_ranks(RANKED, [["d#2", "b#1"], ["z#9"]]) == [2, None]


def test_recall_is_fraction_of_hops_found() -> None:
    hops = [["b#1"], ["e#0"], ["z#9"]]
    assert recall_at_k(RANKED, hops, 2) == pytest.approx(1 / 3)
    assert recall_at_k(RANKED, hops, 5) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, [["j#0"]], 10) == 1.0
    assert recall_at_k(RANKED, [["j#0"]], 9) == 0.0


def test_all_hops_requires_every_hop() -> None:
    assert all_hops_at_k(RANKED, [["a#0"], ["c#0"]], 3)
    assert not all_hops_at_k(RANKED, [["a#0"], ["d#2"]], 3)


def test_reciprocal_rank_uses_first_gold_chunk_of_any_hop() -> None:
    assert reciprocal_rank(RANKED, [["d#2"], ["c#0"]]) == pytest.approx(1 / 3)
    assert reciprocal_rank(RANKED, [["z#9"]]) == 0.0


def test_ndcg_is_one_when_hops_lead_the_ranking() -> None:
    assert ndcg_at_k(RANKED, [["a#0"], ["b#1"]], 10) == pytest.approx(1.0)


def test_ndcg_counts_each_hop_once_even_with_duplicate_gold_chunks() -> None:
    # Both chunks satisfy the same single hop; the second adds no gain.
    assert ndcg_at_k(RANKED, [["a#0", "b#1"]], 10) == pytest.approx(1.0)


def test_ndcg_discounts_lower_ranks() -> None:
    expected = (1 / math.log2(3 + 1)) / (1 / math.log2(2))
    assert ndcg_at_k(RANKED, [["c#0"]], 10) == pytest.approx(expected)
    assert ndcg_at_k(RANKED, [["z#9"]], 10) == 0.0


def test_metrics_reject_items_without_hops() -> None:
    with pytest.raises(ValueError):
        recall_at_k(RANKED, [], 5)

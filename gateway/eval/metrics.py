"""Retrieval metrics over a ranked list of chunk ids, with gold expressed as hops.

Gold for one question is a list of hops (one per evidence entry in the golden set). Each hop
is the set of chunk ids that contain that piece of evidence; retrieving ANY of them satisfies
the hop (a fact stated in two documents can be found in either). Single-hop items have one hop.

- recall@k: fraction of hops satisfied within the top k.
- all_hops@k: every hop satisfied within the top k (a multi-hop item is answerable only then).
- reciprocal rank: 1 / rank of the first retrieved chunk that satisfies any hop.
- nDCG@k: binary gain; a chunk earns gain 1 only if it satisfies a hop not yet satisfied higher
  up, so duplicate copies of one fact are not rewarded twice. The ideal ranking places one chunk
  per hop at the top.
"""

import math
from collections.abc import Sequence

Hops = Sequence[Sequence[str]]


def _check(hops: Hops) -> None:
    if not hops or any(not hop for hop in hops):
        raise ValueError("an answerable item needs at least one hop, each with at least one chunk id")


def hop_ranks(ranked: Sequence[str], hops: Hops) -> list[int | None]:
    """1-based rank of the best-ranked chunk satisfying each hop, or None if not retrieved."""
    _check(hops)
    position = {gid: n for n, gid in reversed(list(enumerate(ranked, 1)))}
    ranks = []
    for hop in hops:
        found = [position[gid] for gid in hop if gid in position]
        ranks.append(min(found) if found else None)
    return ranks


def recall_at_k(ranked: Sequence[str], hops: Hops, k: int) -> float:
    ranks = hop_ranks(ranked, hops)
    return sum(r is not None and r <= k for r in ranks) / len(ranks)


def all_hops_at_k(ranked: Sequence[str], hops: Hops, k: int) -> bool:
    return all(r is not None and r <= k for r in hop_ranks(ranked, hops))


def reciprocal_rank(ranked: Sequence[str], hops: Hops) -> float:
    found = [r for r in hop_ranks(ranked, hops) if r is not None]
    return 1 / min(found) if found else 0.0


def ndcg_at_k(ranked: Sequence[str], hops: Hops, k: int) -> float:
    _check(hops)
    unsatisfied = [set(hop) for hop in hops]
    dcg = 0.0
    for rank, gid in enumerate(ranked[:k], 1):
        for hop in unsatisfied:
            if gid in hop:
                dcg += 1 / math.log2(rank + 1)
                unsatisfied.remove(hop)
                break
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(hops), k) + 1))
    return dcg / ideal

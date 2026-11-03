"""Complexity score from cheap heuristics (spec Phase 4 task 5; EVAL_RESULTS.md, Phase 4 routing).

A weighted sum of features, each scaled to [0, 1]. The weights were fixed by judgement before any
measurement and are not fitted to outcomes; changing them is a new, separately measured policy.
"""

import re
from dataclasses import dataclass

WEIGHTS = {
    "multi_question": 0.25,
    "clauses": 0.15,
    "entities": 0.15,
    "length": 0.10,
    "comparative": 0.10,
    "temporal": 0.05,
    "low_confidence": 0.10,
    "flat_scores": 0.10,
}

_MULTI = re.compile(r",?\s+and\s+(what|how|which|when|who|whom|where|why)\b", re.IGNORECASE)
_CLAUSE_WORDS = frozenset("and or if which that while whereas but because".split())
_COMPARATIVE = frozenset(
    "more less most least higher lower greater fewer larger smaller bigger than versus vs compare "
    "compared comparison difference".split()
)
_TEMPORAL_WORDS = frozenset(
    "before after during since until deadline month months quarter year years".split()
)
_TEMPORAL = re.compile(r"\bby the end\b|\b20\d\d\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019.,%-]*")  # \u2019: curly apostrophe


@dataclass(frozen=True)
class Complexity:
    features: dict[str, float]
    score: float


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def features(question: str, retrieval_scores: list[float]) -> dict[str, float]:
    """Each feature in [0, 1]. retrieval_scores: cosine similarities of the retrieved chunks, best first."""
    words = _WORD.findall(question)
    lower = [w.lower().strip(".,?'\u2019") for w in words]
    entities = sum(
        1 for n, w in enumerate(words) if (n > 0 and w[0].isupper()) or any(ch.isdigit() for ch in w)
    )
    clauses = question.count(",") + sum(1 for w in lower if w in _CLAUSE_WORDS)
    if retrieval_scores:
        top = retrieval_scores[0]
        bottom = retrieval_scores[min(5, len(retrieval_scores) - 1)]
        low_confidence, flat = _clamp(1 - top), _clamp(1 - (top - bottom) / 0.2)
    else:
        low_confidence = flat = 1.0
    return {
        "multi_question": 1.0 if _MULTI.search(question) or question.count("?") > 1 else 0.0,
        "clauses": _clamp(clauses / 3),
        "entities": _clamp(entities / 4),
        "length": _clamp(len(words) / 30),
        "comparative": 1.0 if any(w in _COMPARATIVE for w in lower) else 0.0,
        "temporal": 1.0 if any(w in _TEMPORAL_WORDS for w in lower) or _TEMPORAL.search(question) else 0.0,
        "low_confidence": low_confidence,
        "flat_scores": flat,
    }


def complexity(question: str, retrieval_scores: list[float]) -> Complexity:
    f = features(question, retrieval_scores)
    return Complexity(f, round(sum(WEIGHTS[k] * v for k, v in f.items()), 4))

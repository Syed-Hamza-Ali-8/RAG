"""Deterministic runtime grounding check (CLAUDE.md correction J): no LLM call.

The model cites retrieved chunks by their source label ([S1] … [Sk]); each label maps to
exactly one retrieved chunk ID. An answer with zero valid citations is refused.

Accepted marker styles are only those observed from the model:
- square brackets, optionally grouped: [S1], [ S1 ], [S1, S3]
- lenticular brackets (U+3010/U+3011), gpt-oss's native style: 【S1】, 【 S1 】
Every accepted marker is first rewritten to the canonical form [S1]; validation then runs
on canonical markers only.
"""

import re
from dataclasses import dataclass

_SQUARE = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]", re.IGNORECASE)
_LENTICULAR = re.compile(r"【\s*(S\d+)\s*】", re.IGNORECASE)
_CANONICAL = re.compile(r"\[S(\d+)\]")


@dataclass(frozen=True)
class CitationCheck:
    normalized_text: str  # the answer with every accepted marker rewritten to [S<n>]
    valid_indices: list[int]  # 0-based indices into the retrieved chunks, in first-cited order
    invalid_labels: list[str]

    @property
    def grounded(self) -> bool:
        return bool(self.valid_indices)

    @property
    def rejected_count(self) -> int:
        return len(self.invalid_labels)


def _canonical(labels: str) -> str:
    return "".join(f"[S{int(label.strip()[1:])}]" for label in re.split(r"[,;]", labels))


def normalize_citations(answer: str) -> str:
    answer = _LENTICULAR.sub(lambda m: _canonical(m.group(1)), answer)
    return _SQUARE.sub(lambda m: _canonical(m.group(1)), answer)


def check_citations(answer: str, retrieved_count: int) -> CitationCheck:
    normalized = normalize_citations(answer)
    valid: list[int] = []
    invalid: list[str] = []
    for match in _CANONICAL.finditer(normalized):
        index = int(match.group(1)) - 1
        if 0 <= index < retrieved_count:
            if index not in valid:
                valid.append(index)
        else:
            invalid.append(f"S{match.group(1)}")
    return CitationCheck(normalized, valid, invalid)

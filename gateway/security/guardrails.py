"""Deterministic runtime grounding check (CLAUDE.md correction J): no LLM call.

The model cites retrieved chunks by their source label ([S1] … [Sk]); each label maps to
exactly one retrieved chunk ID. An answer with zero valid citations is refused.
"""

import re
from dataclasses import dataclass

_CITATION = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]", re.IGNORECASE)


@dataclass(frozen=True)
class CitationCheck:
    valid_indices: list[int]  # 0-based indices into the retrieved chunks, in first-cited order
    invalid_labels: list[str]

    @property
    def grounded(self) -> bool:
        return bool(self.valid_indices)


def check_citations(answer: str, retrieved_count: int) -> CitationCheck:
    valid: list[int] = []
    invalid: list[str] = []
    for group in _CITATION.finditer(answer):
        for label in re.split(r"\s*[,;]\s*", group.group(1)):
            index = int(label[1:]) - 1
            if 0 <= index < retrieved_count:
                if index not in valid:
                    valid.append(index)
            else:
                invalid.append(label.upper())
    return CitationCheck(valid, invalid)

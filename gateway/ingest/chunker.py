"""Structure-aware chunker: split on headings, merge consecutive small sections under the same
top-level heading up to the target, then pack whole sentences of oversize sections to a budget.

Budgets are counted with the embedding model's own tokenizer and apply to the text the
embedder actually sees: heading path + content + special tokens (CLAUDE.md correction I).
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from gateway.errors import ChunkTooLarge
from gateway.ingest.loaders import Section

log = logging.getLogger(__name__)

HEADING_SEP = " > "
_SPECIAL_TOKENS = 2  # [CLS] + [SEP]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_LINE_ITEM = re.compile(r"^\s*([-*+]\s|\d+[.)]\s|\|)")


class TokenCounter(Protocol):
    max_seq_len: int

    def count_tokens(self, text: str, *, special_tokens: bool = True) -> int: ...


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    heading_path: str | None
    embed_text: str
    token_count: int  # tokens of embed_text as the model sees it, special tokens included


@dataclass(frozen=True)
class _Unit:
    text: str
    joiner: str  # placed before this unit when it is not first in a chunk
    tokens: int


def build_embed_text(heading_path: str | None, content: str) -> str:
    return f"{heading_path}\n\n{content}" if heading_path else content


def _split_units(text: str) -> Iterable[tuple[str, str]]:
    """Yield (unit_text, joiner). Units are sentences, or whole lines for lists/tables."""
    for p_index, para in enumerate(re.split(r"\n\s*\n", text.strip())):
        lines = [ln.rstrip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        para_joiner = "\n\n" if p_index else ""
        if any(_LINE_ITEM.match(ln) for ln in lines):
            items: list[str] = []
            for ln in lines:
                if _LINE_ITEM.match(ln) or not items:
                    items.append(ln.strip())
                else:
                    items[-1] = f"{items[-1]} {ln.strip()}"
            for i, item in enumerate(items):
                yield item, para_joiner if i == 0 else "\n"
        else:
            joined = " ".join(ln.strip() for ln in lines)
            for i, sentence in enumerate(s for s in _SENTENCE_END.split(joined) if s.strip()):
                yield sentence.strip(), para_joiner if i == 0 else " "


def _force_split(unit: _Unit, budget: int, counter: TokenCounter) -> list[_Unit]:
    """Split one oversize sentence on word boundaries. Only used when a sentence alone exceeds
    the hard max, so it is the single case where a sentence is broken."""
    log.warning("forced split of a %d-token sentence (budget %d)", unit.tokens, budget)
    pieces: list[_Unit] = []
    words: list[str] = []
    used = 0
    for word in unit.text.split():
        n = counter.count_tokens(word, special_tokens=False)
        if n > budget:
            raise ChunkTooLarge(f"single token run of {n} tokens exceeds budget {budget}")
        if words and used + n > budget:
            pieces.append(_Unit(" ".join(words), " ", used))
            words, used = [], 0
        words.append(word)
        used += n
    if words:
        pieces.append(_Unit(" ".join(words), " ", used))
    return [_Unit(pieces[0].text, unit.joiner, pieces[0].tokens), *pieces[1:]]


def _relative_heading(path: tuple[str, ...], anchor: tuple[str, ...]) -> str:
    """`path` with the prefix it shares with `anchor` removed, e.g. "Annual Leave > Carryover"."""
    common = 0
    while common < min(len(path), len(anchor)) and path[common] == anchor[common]:
        common += 1
    return HEADING_SEP.join(path[common:])


def merge_sections(
    sections: Iterable[Section], counter: TokenCounter, *, target_tokens: int
) -> list[Section]:
    """Packing pass: merge consecutive sections under the same top-level heading while the
    merged embed text stays within `target_tokens`. The merged section keeps the first
    section's heading path; each later section's heading is kept inline (relative to that
    path) so the content does not lose its sub-headings. Sections already over the target
    are never merged; they are split by the sentence packer instead."""
    merged: list[Section] = []
    for section in sections:
        if merged:
            prev = merged[-1]
            same_top = prev.heading_path[:1] == section.heading_path[:1]
            if same_top and section.heading_path[:1]:
                inline = _relative_heading(section.heading_path, prev.heading_path)
                body = f"{inline}\n\n{section.text}" if inline else section.text
                text = f"{prev.text}\n\n{body}"
                heading = HEADING_SEP.join(prev.heading_path) or None
                if counter.count_tokens(build_embed_text(heading, text)) <= target_tokens:
                    merged[-1] = Section(prev.heading_path, text)
                    continue
        merged.append(section)
    return merged


def chunk_sections(
    sections: Iterable[Section],
    counter: TokenCounter,
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    if not 0 <= overlap_tokens < target_tokens <= max_tokens <= counter.max_seq_len:
        raise ValueError(
            "need 0 <= overlap < target <= max <= model max sequence length, got "
            f"overlap={overlap_tokens} target={target_tokens} max={max_tokens} "
            f"model_max={counter.max_seq_len}"
        )
    chunks: list[Chunk] = []
    for section in merge_sections(sections, counter, target_tokens=target_tokens):
        heading = HEADING_SEP.join(section.heading_path) or None
        prefix_tokens = counter.count_tokens(build_embed_text(heading, "x"), special_tokens=False) - 1
        target_c = target_tokens - prefix_tokens - _SPECIAL_TOKENS
        max_c = max_tokens - prefix_tokens - _SPECIAL_TOKENS
        if target_c < overlap_tokens + 16:
            raise ChunkTooLarge(f"heading path leaves no room for content: {heading!r}")

        units: list[_Unit] = []
        for text, joiner in _split_units(section.text):
            unit = _Unit(text, joiner, counter.count_tokens(text, special_tokens=False))
            units.extend(_force_split(unit, target_c, counter) if unit.tokens > max_c else [unit])

        for group in _pack(units, target_c, overlap_tokens):
            content = group[0].text + "".join(u.joiner + u.text for u in group[1:])
            embed_text = build_embed_text(heading, content)
            count = counter.count_tokens(embed_text)
            if count > max_tokens or count > counter.max_seq_len:
                raise ChunkTooLarge(
                    f"chunk of {count} tokens exceeds max {max_tokens} "
                    f"(model max {counter.max_seq_len}) in section {heading!r}"
                )
            chunks.append(Chunk(len(chunks), content, heading, embed_text, count))
    return chunks


def _pack(units: list[_Unit], target: int, overlap: int) -> list[list[_Unit]]:
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    used = 0
    fresh = False  # current holds at least one unit not already emitted
    for unit in units:
        if fresh and used + unit.tokens > target:
            groups.append(current)
            carried: list[_Unit] = []
            carried_tokens = 0
            for prev in reversed(current):
                if carried_tokens + prev.tokens > overlap:
                    break
                if carried_tokens + prev.tokens + unit.tokens > target:
                    break
                carried.insert(0, prev)
                carried_tokens += prev.tokens
            current, used = carried, carried_tokens
        current.append(unit)
        used += unit.tokens
        fresh = True
    if fresh:
        groups.append(current)
    return groups

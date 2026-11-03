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


def _common_prefix(paths: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    prefix: tuple[str, ...] | None = None
    for path in paths:
        if prefix is None:
            prefix = path
            continue
        n = 0
        while n < min(len(prefix), len(path)) and prefix[n] == path[n]:
            n += 1
        prefix = prefix[:n]
    return prefix or ()


def _render_group(group: list[Section]) -> Section:
    """One section for `group`: heading path is the members' deepest common prefix; each
    member's remaining sub-heading is kept inline above its text."""
    if len(group) == 1:
        return group[0]
    prefix = _common_prefix(s.heading_path for s in group)
    parts = []
    for s in group:
        inline = HEADING_SEP.join(s.heading_path[len(prefix) :])
        parts.append(f"{inline}\n\n{s.text}" if inline else s.text)
    return Section(prefix, "\n\n".join(parts))


def merge_sections(
    sections: Iterable[Section], counter: TokenCounter, *, target_tokens: int
) -> list[Section]:
    """Packing pass: merge consecutive sections under the same top-level heading while the
    merged embed text stays within `target_tokens`. A merged section's heading path is the
    deepest common prefix of its members, with each member's sub-heading kept inline so the
    content does not lose it. Sections already over the target are never merged; they are
    split by the sentence packer instead."""
    groups: list[list[Section]] = []
    for section in sections:
        if groups and section.heading_path[:1] and groups[-1][0].heading_path[:1] == section.heading_path[:1]:
            candidate = _render_group([*groups[-1], section])
            heading = HEADING_SEP.join(candidate.heading_path) or None
            if counter.count_tokens(build_embed_text(heading, candidate.text)) <= target_tokens:
                groups[-1].append(section)
                continue
        groups.append([section])
    return [_render_group(g) for g in groups]


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

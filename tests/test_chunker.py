import itertools
import re

import pytest

from gateway.errors import ChunkTooLarge
from gateway.ingest.chunker import chunk_sections
from gateway.ingest.embedder import Embedder
from gateway.ingest.loaders import Section


class WordCounter:
    """1 token per whitespace-separated word, +2 special tokens."""

    max_seq_len = 512

    def count_tokens(self, text: str, *, special_tokens: bool = True) -> int:
        return len(text.split()) + (2 if special_tokens else 0)


def sentences(n: int, words: int = 10, start: int = 0) -> list[str]:
    return [" ".join([f"S{i}w{j}" for j in range(words - 1)] + [f"end{i}."]) for i in range(start, start + n)]


def chunk(sections: list[Section], counter: object = None, **kw: int) -> list:  # type: ignore[type-arg]
    params = {"target_tokens": 60, "max_tokens": 80, "overlap_tokens": 15} | kw
    return chunk_sections(sections, counter or WordCounter(), **params)  # type: ignore[arg-type]


def test_respects_token_budget_and_counts_embed_text() -> None:
    text = " ".join(sentences(40))
    chunks = chunk([Section(("Doc", "Part"), text)])
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 80
        assert c.embed_text.startswith("Doc > Part\n\n")
        assert c.token_count == WordCounter().count_tokens(c.embed_text)


def test_never_splits_mid_sentence() -> None:
    source = sentences(40)
    chunks = chunk([Section((), " ".join(source))])
    for c in chunks:
        pieces = re.split(r"(?<=\.)\s+", c.content)
        assert all(p in source for p in pieces), c.content


def test_overlap_carries_trailing_whole_sentences() -> None:
    chunks = chunk([Section((), " ".join(sentences(40)))])
    for prev, nxt in itertools.pairwise(chunks):
        last_sentence = re.split(r"(?<=\.)\s+", prev.content)[-1]
        assert nxt.content.startswith(last_sentence)


def test_overlap_disabled() -> None:
    chunks = chunk([Section((), " ".join(sentences(40)))], overlap_tokens=0)
    joined = " ".join(c.content for c in chunks)
    assert joined == " ".join(sentences(40))


def test_merged_chunk_takes_deepest_common_prefix_and_keeps_subheadings_inline() -> None:
    chunks = chunk(
        [
            Section(("Leave Policy", "Scope"), "All staff."),
            Section(("Leave Policy", "Annual Leave"), "Twenty two days."),
            Section(("Leave Policy", "Sick Leave"), "Ten days."),
        ]
    )
    (only,) = chunks
    assert only.heading_path == "Leave Policy"
    assert only.content == (
        "Scope\n\nAll staff.\n\nAnnual Leave\n\nTwenty two days.\n\nSick Leave\n\nTen days."
    )
    assert only.embed_text.startswith("Leave Policy\n\nScope\n\n")


def test_common_prefix_can_be_deeper_than_top_level() -> None:
    (only,) = chunk(
        [
            Section(("Policy", "Annual", "Accrual"), "Monthly."),
            Section(("Policy", "Annual", "Carryover"), "Five days."),
        ]
    )
    assert only.heading_path == "Policy > Annual"
    assert only.content == "Accrual\n\nMonthly.\n\nCarryover\n\nFive days."


def test_small_sibling_sections_merge_under_parent_heading() -> None:
    chunks = chunk(
        [
            Section(("Policy",), "Intro text."),
            Section(("Policy", "Annual"), "Twenty days."),
            Section(("Policy", "Annual", "Carryover"), "Five days."),
            Section(("Policy", "Sick"), "Ten days."),
        ]
    )
    (only,) = chunks
    assert only.heading_path == "Policy"
    assert only.content == (
        "Intro text.\n\nAnnual\n\nTwenty days.\n\nAnnual > Carryover\n\nFive days.\n\nSick\n\nTen days."
    )
    assert only.ordinal == 0


def test_never_merges_across_top_level_heading() -> None:
    chunks = chunk([Section(("A",), "Alpha one."), Section(("B",), "Beta one."), Section((), "Loose.")])
    assert [c.heading_path for c in chunks] == ["A", "B", None]
    assert [c.ordinal for c in chunks] == [0, 1, 2]


def test_merge_stops_before_exceeding_target() -> None:
    # target 60 with WordCounter: each section is 2 (heading) + 20 words + 2 specials ≈ 24 tokens
    sections = [Section(("Doc", f"S{i}"), " ".join(sentences(2))) for i in range(6)]
    chunks = chunk(sections, overlap_tokens=0)
    assert 1 < len(chunks) < 6
    assert all(c.token_count <= 60 for c in chunks)
    assert chunks[0].heading_path == "Doc"
    assert chunks[0].content.startswith("S0\n\n")
    assert sum(c.content.count("end1.") for c in chunks) == 6  # no text lost or duplicated


def test_oversize_section_is_not_merged_and_is_split_by_sentences() -> None:
    big = " ".join(sentences(20))
    chunks = chunk([Section(("Doc", "Small"), "Tiny."), Section(("Doc", "Big"), big)])
    assert chunks[0].content == "Tiny."
    assert all(c.heading_path == "Doc > Big" for c in chunks[1:])
    assert all(c.token_count <= 80 for c in chunks)


def test_list_items_are_kept_whole() -> None:
    items = "\n".join(f"- item {i} with some words here" for i in range(30))
    chunks = chunk([Section((), items)], overlap_tokens=0)
    for c in chunks:
        assert all(line.startswith("- item") for line in c.content.split("\n"))


def test_oversize_sentence_is_force_split_within_budget() -> None:
    giant = " ".join(f"w{i}" for i in range(200)) + "."
    chunks = chunk([Section((), giant)])
    assert len(chunks) >= 3
    assert all(c.token_count <= 80 for c in chunks)


def test_rejects_inconsistent_budgets() -> None:
    with pytest.raises(ValueError):
        chunk([Section((), "x.")], target_tokens=100, max_tokens=80)
    with pytest.raises(ValueError):
        chunk([Section((), "x.")], max_tokens=600)  # above model max 512


def test_heading_too_long_raises() -> None:
    with pytest.raises(ChunkTooLarge):
        chunk([Section(tuple(["word " * 10] * 5), "Body.")])


def test_real_tokenizer_keeps_every_chunk_under_model_max(embedder: Embedder) -> None:
    long_text = " ".join(
        f"Clause {i} states that the supplier shall indemnify the customer against third-party claims."
        for i in range(400)
    )
    chunks = chunk_sections(
        [Section(("Contract", "Indemnity"), long_text)],
        embedder,
        target_tokens=384,
        max_tokens=450,
        overlap_tokens=64,
    )
    assert len(chunks) > 5
    for c in chunks:
        assert c.token_count <= 450 < embedder.max_seq_len
        assert c.token_count == embedder.count_tokens(c.embed_text)

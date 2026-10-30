"""Harness tests: subset selection, aggregation, labelling, and one end-to-end item with stub LLMs."""

import argparse
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import pytest
from openai.types.chat import ChatCompletionMessageParam

from gateway.config import Settings
from gateway.ingest.embedder import Embedder
from gateway.ingest.pipeline import ingest_document
from gateway.llm.provider import Completion
from gateway.main import create_app
from run_eval import (
    aggregate,
    budget_check,
    evaluate_item,
    finalize_meta,
    load_golden,
    mode_name,
    read_partial,
    run,
    select_subset,
    stratum,
)
from tests.conftest import StubLLM

GOLDEN = load_golden()


def test_subset_is_reproducible_and_stratified() -> None:
    first, second = select_subset(GOLDEN, 25), select_subset(GOLDEN, 25)
    assert [i["id"] for i in first] == [i["id"] for i in second]
    assert len(first) == 25
    assert Counter(stratum(i) for i in first) == {
        "buried_fact": 5,
        "single_other": 7,
        "multi_hop": 6,
        "unanswerable": 3,
        "near_miss": 4,
    }
    pairs = Counter(i["pair"] for i in first if i["type"] == "near_miss")
    assert set(pairs.values()) == {2}  # near-miss pairs are never split


def test_only_the_fixed_subset_size_is_allowed() -> None:
    with pytest.raises(ValueError):
        select_subset(GOLDEN, 30)


def test_mode_names_label_every_run() -> None:
    assert mode_name(None, False) == "full"
    assert mode_name(25, False) == "subset25"
    assert mode_name(25, True) == "retrieval-subset25"
    assert mode_name(None, True) == "retrieval-full"


@pytest.mark.parametrize("flags", [{"subset": 25}, {"retrieval_only": True}])
async def test_baseline_requires_a_full_judged_run(flags: dict[str, Any]) -> None:
    args = argparse.Namespace(subset=None, retrieval_only=False, baseline="Phase 2", delay_ms=0, resume=None)
    for k, v in flags.items():
        setattr(args, k, v)
    with pytest.raises(SystemExit, match="--baseline requires a full run"):
        await run(args, GOLDEN, None)


def rec(rid: str, rtype: str, recall6: float, refused: bool | None = None, **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "id": rid,
        "type": rtype,
        "tags": extra.pop("tags", []),
        "pair": extra.pop("pair", None),
    }
    if rtype != "unanswerable":
        r["retrieval"] = {
            "recall@5": recall6,
            "recall@6": recall6,
            "recall@10": 1.0,
            "all_hops@10": True,
            "mrr": 0.5,
            "ndcg@10": 0.6,
        }
    if refused is not None:
        r["refused"] = refused
    r.update(extra)
    return r


def verdict(correct: bool, faithful: bool = True) -> dict[str, Any]:
    return {
        "faithful": faithful,
        "relevant": True,
        "correct": correct,
        "unsupported_claims": [],
        "reason": "",
    }


def test_aggregate_rates_and_buried_group() -> None:
    records = [
        rec("a", "single_hop", 1.0, False, tags=["buried_fact"], judge=verdict(True)),
        rec("b", "single_hop", 0.0, True, tags=["buried_fact"]),
        rec("c", "multi_hop", 0.5, False, judge=verdict(False, faithful=False)),
        rec("d", "unanswerable", 0, True),
        rec("e", "unanswerable", 0, False, judge=verdict(False)),
        rec("f", "near_miss", 1.0, False, pair="nm1", judge=verdict(True)),
        rec("g", "near_miss", 1.0, False, pair="nm1", judge=verdict(False)),
    ]
    agg = aggregate(records)
    assert agg["retrieval"]["buried_fact"]["recall@6"] == 0.5
    assert agg["retrieval"]["all_answerable"]["n"] == 5
    g = agg["generation"]
    assert g["correct_refusal_unanswerable"] == {"rate": 0.5, "n": 2, "count": 1}
    assert g["false_refusal_answerable"]["count"] == 1
    assert g["correct_answerable"] == {"rate": 0.4, "n": 5, "count": 2}  # the refusal counts as not correct
    assert g["near_miss_pairs_both_correct"] == {"rate": 0.0, "n": 1, "count": 0}
    assert g["hallucinated_on_unanswerable"] == ["e"]
    assert g["refused_answerable"] == ["b"]


def test_retrieval_only_records_have_no_generation_block() -> None:
    assert "generation" not in aggregate([rec("a", "single_hop", 1.0)])


class StubJudge(StubLLM):
    tier = "large"
    model_id = "stub-judge"

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
        self.calls.append(messages)
        return Completion(
            '{"faithful": true, "relevant": true, "correct": true, "citations_supported": true, '
            '"unsupported_claims": [], "miscited": [], "reason": "ok"}',
            self.model_id,
            prompt_tokens=10,
            completion_tokens=5,
        )


@pytest.fixture
async def eval_app(
    settings: Settings, pool: asyncpg.Pool, embedder: Embedder, tmp_path: Path, stub_llm: StubLLM
) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    async with pool.acquire() as conn:
        tenant_id: UUID = await conn.fetchval(
            "INSERT INTO tenants (slug, name) VALUES ('evalco', 'EvalCo') "
            "ON CONFLICT (slug) DO UPDATE SET name = 'EvalCo' RETURNING id"
        )
        await conn.execute(
            "INSERT INTO users (tenant_id, email, roles, clearance) VALUES ($1, 'hr@evalco.example', $2, 1) "
            "ON CONFLICT (tenant_id, email) DO NOTHING",
            tenant_id,
            ["employee", "hr"],
        )
    doc = tmp_path / "leave.md"
    doc.write_text(
        "# Leave Policy\n\n## Annual\n\nStaff receive 21 days of annual leave.\n", encoding="utf-8"
    )
    await ingest_document(pool, embedder, settings, tenant_id=tenant_id, slug="hr-leave-policy", path=doc)
    app = create_app(settings, llm=stub_llm, embedder=embedder)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            yield app, client


async def test_evaluate_item_end_to_end_with_stubs(
    eval_app: tuple[Any, httpx.AsyncClient], settings: Settings, stub_llm: StubLLM
) -> None:
    app, client = eval_app
    item = {
        "id": "t1",
        "type": "single_hop",
        "tags": [],
        "tenant": "evalco",
        "as_user": "hr@evalco.example",
        "question": "How much annual leave do staff get?",
        "expected_answer": "21 days.",
        "evidence": [{"text": "21 days", "chunk_ids": ["hr-leave-policy#0"]}],
        "gold_chunk_ids": ["hr-leave-policy#0"],
    }
    judge = StubJudge()
    record = await evaluate_item(item, client, app.state.pool, app.state, judge, settings, delay_s=0)
    assert record["retrieved"][0] == "hr-leave-policy#0"
    assert record["retrieval"]["recall@6"] == 1.0
    assert record["refused"] is False and record["citations"] == ["hr-leave-policy#0"]
    assert record["judge"]["correct"] is True and record["judge"]["raw"].startswith("{")
    assert record["judge"]["citations_supported"] is True
    assert record["query_log_id"] is not None
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT purpose, model_used, prompt_tokens, completion_tokens, prompt_version, answer_raw "
            "FROM query_log WHERE id = $1",
            record["judge_query_log_id"],
        )
    assert row["purpose"] == "eval_judge" and row["model_used"] == "stub-judge"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (10, 5)
    assert row["prompt_version"].startswith("judge-v") and row["answer_raw"].startswith("{")
    judged_text = str(judge.calls[0][1]["content"])
    assert "21 days of annual leave" in judged_text and "<reference_answer>\n21 days.\n" in judged_text


async def test_evaluate_item_retrieval_only_makes_no_llm_calls(
    eval_app: tuple[Any, httpx.AsyncClient], settings: Settings, stub_llm: StubLLM
) -> None:
    app, client = eval_app
    item = {
        "id": "t2",
        "type": "single_hop",
        "tags": [],
        "tenant": "evalco",
        "as_user": "hr@evalco.example",
        "question": "Annual leave?",
        "expected_answer": "21 days.",
        "evidence": [{"text": "21 days", "chunk_ids": ["hr-leave-policy#0"]}],
    }
    record = await evaluate_item(item, client, app.state.pool, app.state, None, settings, delay_s=0)
    assert "refused" not in record and record["retrieval"]["recall@10"] == 1.0
    assert stub_llm.calls == []


def test_finalize_meta_keeps_original_start_and_accumulates_sessions() -> None:
    meta = {"run_id": "r1", "started_utc": "2026-10-23T17:15:25+00:00", "git_commit": "a9784a8"}
    sessions = [
        {
            "started_utc": "2026-10-23T17:15:25+00:00",
            "elapsed_min": 41.5,
            "git_commit": "a9784a8",
            "stopped": "429",
        },
        {
            "started_utc": "2026-10-23T18:05:15+00:00",
            "elapsed_min": 58.1,
            "git_commit": "a9784a8-dirty",
            "stopped": None,
        },
    ]
    out = finalize_meta(meta, sessions, "2026-10-23T19:03:11+00:00")
    assert out["started_utc"] == "2026-10-23T17:15:25+00:00"
    assert out["elapsed_min"] == 99.6
    assert out["git_commits"] == ["a9784a8", "a9784a8-dirty"]
    assert out["finished_utc"] == "2026-10-23T19:03:11+00:00" and len(out["sessions"]) == 2


def test_read_partial_separates_records_from_session_lines(tmp_path: Path) -> None:
    f = tmp_path / "x.partial.jsonl"
    f.write_text(
        '{"meta": {"run_id": "r1"}}\n{"id": "q001"}\n{"session": {"elapsed_min": 3.0}}\n{"id": "q002"}\n',
        encoding="utf-8",
    )
    meta, records, sessions = read_partial(f)
    assert meta == {"run_id": "r1"}
    assert [r["id"] for r in records] == ["q001", "q002"]
    assert sessions == [{"elapsed_min": 3.0}]


def test_budget_check() -> None:
    assert budget_check(used=150_000, per_call=2500, calls=20, limit=200_000) == (50_000, 50_000, True)
    assert budget_check(used=150_000, per_call=2500, calls=21, limit=200_000) == (52_500, 50_000, False)


def _stack(monkeypatch: pytest.MonkeyPatch, others: list[str]) -> None:
    import run_eval
    from gateway.stack import StackStatus

    status = StackStatus(services={"postgres": "healthy", "redis": "healthy"}, other_containers=others)
    monkeypatch.setattr(run_eval, "check_stack", lambda: status)


def test_strict_preflight_refuses_other_containers_without_force(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from run_eval import require_stack

    _stack(monkeypatch, ["case_app_dev", "odoo_db"])
    with pytest.raises(SystemExit, match="docker stop case_app_dev odoo_db") as exc:
        require_stack(strict=True)
    assert "--force-containers" in str(exc.value)
    require_stack(strict=True, force_containers=True)
    assert "proceeding anyway" in capsys.readouterr().out
    require_stack()  # non-strict callers (calibrate_judge) only warn


def test_strict_preflight_passes_on_a_clean_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    from run_eval import require_stack

    _stack(monkeypatch, [])
    require_stack(strict=True)


def test_day_plan_stops_at_the_first_item_either_model_cannot_afford() -> None:
    from run_eval import BUDGET_MARGIN, affordable_items

    items = [{"type": "single_hop"}, {"type": "unanswerable"}, {"type": "single_hop"}, {"type": "single_hop"}]
    cost = {"query": 1000.0, "eval_judge": 2000.0}
    gen, judge = round(1000 * BUDGET_MARGIN), round(2000 * BUDGET_MARGIN)
    plenty = 10**6
    assert affordable_items(items, {"g": plenty, "j": plenty}, "g", "j", cost) == 4
    # Judge budget for two answerable items: the unanswerable one in between needs no judge call.
    assert affordable_items(items, {"g": plenty, "j": 2 * judge}, "g", "j", cost) == 3
    # Generator budget for exactly two items stops at the third, whatever the judge has left.
    assert affordable_items(items, {"g": 2 * gen, "j": plenty}, "g", "j", cost) == 2
    assert affordable_items(items, {"g": 0, "j": plenty}, "g", "j", cost) == 0


def test_item_cost_judges_only_answerable_items() -> None:
    from run_eval import BUDGET_MARGIN, item_cost

    cost = {"query": 1000.0, "eval_judge": 2000.0}
    assert item_cost({"type": "unanswerable"}, "g", "j", cost) == {"g": 1000 * BUDGET_MARGIN}
    assert item_cost({"type": "multi_hop"}, "g", "j", cost) == {
        "g": 1000 * BUDGET_MARGIN,
        "j": 2000 * BUDGET_MARGIN,
    }


def test_truncation_is_neither_a_refusal_nor_a_hallucination() -> None:
    records = [
        rec("a", "single_hop", 1.0, False, judge=verdict(True)),
        rec("b", "single_hop", 1.0, True),
        rec("c", "multi_hop", 1.0, False, truncated=True),
        rec("u1", "unanswerable", 0, True),
        rec("u2", "unanswerable", 0, False, truncated=True),
    ]
    g = aggregate(records)["generation"]
    assert g["false_refusal_answerable"] == {"rate": 0.5, "n": 2, "count": 1}  # c is not in the denominator
    assert g["correct_refusal_unanswerable"] == {"rate": 1.0, "n": 1, "count": 1}  # nor is u2
    assert g["hallucinated_on_unanswerable"] == []
    assert g["truncated_generations"] == {"rate": 0.4, "n": 5, "count": 2}
    assert g["truncated_items"] == ["c", "u2"]
    assert g["correct_answerable"] == {"rate": round(1 / 3, 4), "n": 3, "count": 1}  # c counts as not correct
    assert g["refused_answerable"] == ["b"]


async def test_truncated_judge_call_is_logged_and_recorded_as_a_judge_error(
    eval_app: tuple[Any, httpx.AsyncClient], settings: Settings
) -> None:
    from gateway.errors import TruncatedCompletion

    class CutOffJudge(StubJudge):
        async def complete(self, messages: list[ChatCompletionMessageParam]) -> Completion:
            raise TruncatedCompletion("stub-judge", 2500, 1500, '{"faithful": tr')

    app, client = eval_app
    item = {
        "id": "t3",
        "type": "single_hop",
        "tags": [],
        "tenant": "evalco",
        "as_user": "hr@evalco.example",
        "question": "How much annual leave do staff get?",
        "expected_answer": "21 days.",
        "evidence": [{"text": "21 days", "chunk_ids": ["hr-leave-policy#0"]}],
    }
    record = await evaluate_item(item, client, app.state.pool, app.state, CutOffJudge(), settings, delay_s=0)
    assert "judge" not in record and "completion limit" in record["judge_error"]
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT purpose, outcome, completion_tokens FROM query_log WHERE id = $1",
            record["judge_query_log_id"],
        )
    assert (row["purpose"], row["outcome"], row["completion_tokens"]) == ("eval_judge", "truncated", 1500)


def test_aggregate_reports_cache_hits_separately() -> None:
    records = [
        rec("a", "single_hop", 1.0, False, judge=verdict(True), cache_hit=False),
        rec("b", "single_hop", 1.0, False, judge=verdict(True), cache_hit=True),
        rec("c", "single_hop", 1.0, False, judge=verdict(True), cache_hit=None),  # bypassed: not consulted
    ]
    g = aggregate(records)["generation"]
    assert (g["cache_consulted"], g["cache_hit_items"]) == (2, ["b"])

"""Golden-set evaluation harness (Phase 2).

    uv run python eval/run_eval.py --subset 25          # fixed stratified 25-item sample (iteration)
    uv run python eval/run_eval.py                      # full 100-item run
    uv run python eval/run_eval.py --baseline "Phase 2" # full run, recorded in EVAL_RESULTS.md
    uv run python eval/run_eval.py --retrieval-only     # retrieval metrics only, no LLM calls
    uv run python eval/run_eval.py --resume eval/results/<run>.partial.jsonl

Per question: vector retrieval at top 10 (the same search /v1/query uses) for retrieval metrics;
POST /v1/query in-process for the answer (writes query_log, including answer_raw); then one judge
call per non-refused answer. Every LLM call is followed by EVAL_REQUEST_DELAY_MS. Records are
appended to a .partial.jsonl after each question, so a run stopped by rate limits can resume.
Results go to eval/results/<UTC stamp>_<mode>.json, labelled with the mode. Only full runs with
judging may become a baseline in EVAL_RESULTS.md (CLAUDE.md, Phase 2 rules).
"""

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from gateway.config import Settings, get_settings
from gateway.deps import auth_for_email
from gateway.errors import LLMProviderError, TruncatedCompletion
from gateway.llm.prompts import PROMPT_VERSION
from gateway.llm.provider import Completion, OpenAICompatibleLLM
from gateway.main import create_app
from gateway.query_log import QueryLogEntry, write_query_log
from gateway.retrieval.vector import RetrievedChunk, vector_search
from gateway.security.tokens import issue_token
from gateway.stack import StackNotReady, check_stack, describe
from judge import JUDGE_PROMPT_VERSION, JudgeParseError, Source, call_judge, parse_verdict
from metrics import all_hops_at_k, hop_ranks, ndcg_at_k, recall_at_k, reciprocal_rank

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
GOLDEN = EVAL_DIR / "golden_set.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
BASELINES_DIR = EVAL_DIR / "baselines"
EVAL_RESULTS_MD = ROOT / "EVAL_RESULTS.md"

RETRIEVE_K = 10
# Pre-flight fallback when query_log has no recent calls to average over (tokens per call).
DEFAULT_TOKENS_PER_CALL = {"query": 2600, "eval_judge": 4000}
# Per-call estimates are averages; budget planning inflates them so one long item cannot cross the cap.
BUDGET_MARGIN = 1.25
SUBSET_SEED = "gateway-subset-v1"
# Fixed allocation for --subset 25, proportional to the full set (strata sizes 20/30/25/15/10).
# Near-miss items are drawn as whole pairs. Changing this changes the subset: bump SUBSET_SEED.
SUBSET_ALLOCATION = {
    25: {"buried_fact": 5, "single_other": 7, "multi_hop": 6, "unanswerable": 3, "near_miss_pairs": 2}
}


def require_stack(*, strict: bool = False, force_containers: bool = False) -> None:
    """Container pre-flight (gateway.stack): refuse to start on a stack that is down. With strict, also
    refuse while other projects' containers are running (they share the machine's ~3.8 GB of RAM),
    unless --force-containers: a warning alone was ignored twice."""
    try:
        status = check_stack()
    except StackNotReady as exc:
        raise SystemExit(f"pre-flight: {exc}") from exc
    if not (strict and status.other_containers):
        print(describe(status))
        return
    names = " ".join(status.other_containers)
    message = (
        f"pre-flight: {len(status.other_containers)} non-Gateway container(s) running: {names}\n"
        f"Stop them first (stop only, never remove; restart list in docs/stopped_containers.txt):\n"
        f"  docker stop {names}"
    )
    if not force_containers:
        raise SystemExit(message + "\nor pass --force-containers to run alongside them.")
    print(message + "\nproceeding anyway: --force-containers given (the token-budget check still applies).")


class HarnessStopped(Exception):
    """The run cannot continue (rate limit, provider failure); progress is saved in the partial file."""


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def golden_hash(path: Path = GOLDEN) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def stratum(item: dict[str, Any]) -> str:
    if item["type"] == "single_hop":
        return "buried_fact" if "buried_fact" in item["tags"] else "single_other"
    return str(item["type"])


def _key(name: str) -> str:
    return hashlib.sha256(f"{SUBSET_SEED}:{name}".encode()).hexdigest()


def select_subset(items: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Deterministic stratified sample: same ids every time for the same golden set and seed."""
    if size not in SUBSET_ALLOCATION:
        raise ValueError(f"--subset supports {sorted(SUBSET_ALLOCATION)} only (fixed, reproducible samples)")
    alloc = SUBSET_ALLOCATION[size]
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_stratum[stratum(item)].append(item)
    chosen: list[dict[str, Any]] = []
    for name in ("buried_fact", "single_other", "multi_hop", "unanswerable"):
        chosen += sorted(by_stratum[name], key=lambda i: _key(i["id"]))[: alloc[name]]
    pairs = sorted({i["pair"] for i in by_stratum["near_miss"]}, key=_key)[: alloc["near_miss_pairs"]]
    chosen += [i for i in by_stratum["near_miss"] if i["pair"] in pairs]
    ids = {i["id"] for i in chosen}
    return [i for i in items if i["id"] in ids]


def hops(item: dict[str, Any]) -> list[list[str]]:
    return [ev["chunk_ids"] for ev in item["evidence"]]


def retrieval_metrics(ranked: list[str], item: dict[str, Any]) -> dict[str, Any]:
    h = hops(item)
    return {
        "hop_ranks": hop_ranks(ranked, h),
        "recall@5": recall_at_k(ranked, h, 5),
        "recall@6": recall_at_k(ranked, h, 6),
        "recall@10": recall_at_k(ranked, h, 10),
        "all_hops@10": all_hops_at_k(ranked, h, 10),
        "mrr": reciprocal_rank(ranked, h),
        "ndcg@10": ndcg_at_k(ranked, h, 10),
    }


def _mean(values: Iterable[float]) -> float | None:
    vals = list(values)
    return round(statistics.mean(vals), 4) if vals else None


def _rate(flags: list[bool]) -> dict[str, Any]:
    return {
        "rate": round(sum(flags) / len(flags), 4) if flags else None,
        "n": len(flags),
        "count": sum(flags),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in records if r["type"] != "unanswerable"]
    groups: dict[str, list[dict[str, Any]]] = {"all_answerable": answerable}
    for r in answerable:
        groups.setdefault(r["type"], []).append(r)
        if "buried_fact" in r["tags"]:
            groups.setdefault("buried_fact", []).append(r)
    retrieval = {
        name: {
            "n": len(rs),
            **{
                m: _mean(r["retrieval"][m] for r in rs)
                for m in ("recall@5", "recall@6", "recall@10", "mrr", "ndcg@10")
            },
            "all_hops@10": _mean(float(r["retrieval"]["all_hops@10"]) for r in rs),
        }
        for name, rs in groups.items()
    }
    out: dict[str, Any] = {"retrieval": retrieval}
    generated = [r for r in records if "refused" in r]
    if generated:
        # A truncated generation (TruncatedCompletion) is neither an answer nor a refusal: it is left out of
        # both refusal rates and the hallucination check, counts as not correct, and is reported on its own.
        truncated = [r for r in generated if r.get("truncated")]
        completed = [r for r in generated if not r.get("truncated")]
        unanswerable = [r for r in completed if r["type"] == "unanswerable"]
        ans = [r for r in generated if r["type"] != "unanswerable"]
        ans_completed = [r for r in ans if not r.get("truncated")]
        judged = [r for r in generated if r.get("judge")]
        pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in ans:
            if r.get("pair"):
                pairs[r["pair"]].append(r)
        out["generation"] = {
            "correct_refusal_unanswerable": _rate([r["refused"] for r in unanswerable]),
            "false_refusal_answerable": _rate([r["refused"] for r in ans_completed]),
            "truncated_generations": _rate([bool(r.get("truncated")) for r in generated]),
            "faithful": _rate([r["judge"]["faithful"] for r in judged]),
            "relevant": _rate([r["judge"]["relevant"] for r in judged]),
            # judge-v2 only; judge-v1 verdicts have no citation check, so they are excluded, not counted.
            "citations_supported": _rate(
                [r["judge"]["citations_supported"] for r in judged if "citations_supported" in r["judge"]]
            ),
            # Correctness over all answerable items: a refusal counts as not correct.
            "correct_answerable": _rate([bool(r.get("judge") and r["judge"]["correct"]) for r in ans]),
            "near_miss_pairs_both_correct": _rate(
                [all(bool(r.get("judge") and r["judge"]["correct"]) for r in rs) for rs in pairs.values()]
            ),
            "judge_errors": sum(1 for r in generated if r.get("judge_error")),
            "hallucinated_on_unanswerable": [r["id"] for r in unanswerable if not r["refused"]],
            "refused_answerable": [r["id"] for r in ans if r["refused"]],
            "truncated_items": [r["id"] for r in truncated],
        }
    return out


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT)
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
    return result.stdout.strip() + ("-dirty" if dirty.strip() else "")


def mode_name(subset: int | None, retrieval_only: bool) -> str:
    base = f"subset{subset}" if subset else "full"
    return f"retrieval-{base}" if retrieval_only else base


async def resolve_gold_uuids(
    conn: asyncpg.Connection, items: list[dict[str, Any]]
) -> dict[tuple[str, str], str]:
    """Correction F: gold ids are slug#ordinal; resolve them to chunk UUIDs, failing on any stale id."""
    rows = await conn.fetch(
        """
        SELECT t.slug AS tenant, d.slug || '#' || c.ordinal AS gid, c.id::text AS uuid
        FROM chunks c JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id
        """
    )
    known = {(r["tenant"], r["gid"]): r["uuid"] for r in rows}
    stale = sorted({(i["tenant"], g) for i in items for g in i["gold_chunk_ids"]} - known.keys())
    if stale:
        raise SystemExit(f"stale gold ids (run eval/verify_golden.py): {stale[:5]}")
    return known


def gid(chunk: RetrievedChunk) -> str:
    return f"{chunk.document_slug}#{chunk.ordinal}"


async def log_judge_call(
    pool: asyncpg.Pool,
    tenant_id: Any,
    judge_llm: OpenAICompatibleLLM,
    completion: Completion,
    llm_ms: int,
    outcome: str = "answered",
) -> int:
    """Record a judge call in query_log (purpose 'eval_judge') so its tokens count against the judge
    model's daily budget in the pre-flight check. answer_raw holds the raw judge output."""
    async with pool.acquire() as conn:
        await write_query_log(
            conn,
            QueryLogEntry(
                tenant_id=tenant_id,
                route_tier=judge_llm.tier,
                model_used=completion.model,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                retrieval_ms=0,
                llm_ms=llm_ms,
                total_ms=llm_ms,
                refused=False,
                answer_raw=completion.text,
                citations_valid=None,
                citations_rejected=None,
                prompt_version=JUDGE_PROMPT_VERSION,
                purpose="eval_judge",
                outcome=outcome,
            ),
        )
        log_id: int = await conn.fetchval(
            "SELECT max(id) FROM query_log WHERE tenant_id = $1 AND purpose = 'eval_judge'", tenant_id
        )
    return log_id


async def judge_and_log(
    pool: asyncpg.Pool,
    tenant_id: Any,
    judge_llm: OpenAICompatibleLLM,
    question: str,
    reference_answer: str,
    sources: list[Source],
    answer: str,
    delay_s: float,
) -> dict[str, Any]:
    """One paced judge call, always logged. Returns {"judge": ...} or {"judge_error": ...}, plus the
    query_log id. Raises HarnessStopped on provider failure (rate limits included)."""
    started = time.perf_counter()
    try:
        completion = await call_judge(judge_llm, question, reference_answer, sources, answer)
    except LLMProviderError as exc:
        detail = exc.describe() if hasattr(exc, "describe") else str(exc)
        raise HarnessStopped(f"judge call failed: {detail}") from exc
    except TruncatedCompletion as exc:
        # Its tokens still count against the judge budget, so it is logged; the verdict is a judge error.
        llm_ms = round((time.perf_counter() - started) * 1000)
        cut = Completion(exc.text, exc.model, exc.prompt_tokens, exc.completion_tokens)
        await asyncio.sleep(delay_s)
        return {
            "judge_query_log_id": await log_judge_call(pool, tenant_id, judge_llm, cut, llm_ms, "truncated"),
            "judge_error": str(exc),
            "judge_raw": exc.text,
        }
    llm_ms = round((time.perf_counter() - started) * 1000)
    await asyncio.sleep(delay_s)
    out: dict[str, Any] = {
        "judge_query_log_id": await log_judge_call(pool, tenant_id, judge_llm, completion, llm_ms)
    }
    try:
        verdict = parse_verdict(completion.text)
        out["judge"] = {**verdict.__dict__, "raw": completion.text}
    except JudgeParseError as exc:
        out["judge_error"] = str(exc)
        out["judge_raw"] = completion.text
    return out


async def evaluate_item(
    item: dict[str, Any],
    client: httpx.AsyncClient,
    pool: asyncpg.Pool,
    app_state: Any,
    judge_llm: OpenAICompatibleLLM | None,
    settings: Settings,
    delay_s: float,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        k: item.get(k)
        for k in ("id", "type", "tags", "tenant", "as_user", "pair", "question", "expected_answer")
    }
    # Every item is asked as its seeded user: retrieval metrics use that user's ACL filter (Phase 3+).
    async with pool.acquire() as conn:
        auth = await auth_for_email(conn, item["tenant"], item["as_user"])
        tenant_id = auth.tenant_id
        query_vec = await app_state.embedder.embed_query(item["question"])
        chunks = await vector_search(conn, acl_filter=auth.acl(), query_embedding=query_vec, top_k=RETRIEVE_K)
    ranked = [gid(c) for c in chunks]
    record["retrieved"] = ranked
    if item["type"] != "unanswerable":
        record["retrieval"] = retrieval_metrics(ranked, item)
    if judge_llm is None:  # retrieval-only run
        return record

    token = issue_token(settings, user_id=auth.user_id, tenant_id=auth.tenant_id)
    response = await client.post(
        "/v1/query", json={"question": item["question"]}, headers={"Authorization": f"Bearer {token}"}
    )
    await asyncio.sleep(delay_s)
    if response.status_code == 502 and response.json().get("error") == "llm_truncated":
        # Neither answered nor refused: recorded as its own outcome, never judged.
        async with pool.acquire() as conn:
            record["query_log_id"] = await conn.fetchval(
                "SELECT max(id) FROM query_log WHERE tenant_id = $1", tenant_id
            )
        record.update(truncated=True, refused=False, answer=None, citations=[])
        return record
    if response.status_code != 200:
        raise HarnessStopped(
            f"{item['id']}: /v1/query returned {response.status_code}: {response.text[:300]}"
        )
    body = response.json()
    async with pool.acquire() as conn:
        record["query_log_id"] = await conn.fetchval(
            "SELECT max(id) FROM query_log WHERE tenant_id = $1", tenant_id
        )
    top = chunks[: settings.retrieval_top_k]
    by_uuid = {str(c.chunk_id): c for c in top}
    cited = [by_uuid.get(c["chunk_id"]) for c in body["citations"]]
    if any(c is None for c in cited):
        raise HarnessStopped(
            f"{item['id']}: answer cites chunks outside the harness's top {settings.retrieval_top_k}"
        )
    record.update(
        answer=body["answer"],
        refused=body["refused"],
        citations=[gid(c) for c in cited if c is not None],
        model=body["model"],
        prompt_version=body["prompt_version"],
        timings=body["timings"],
    )
    if body["refused"]:
        return record

    sources = [Source(f"S{n}", c.document_title, c.content) for n, c in enumerate(top, 1)]
    try:
        record.update(
            await judge_and_log(
                pool,
                tenant_id,
                judge_llm,
                item["question"],
                item["expected_answer"],
                sources,
                body["answer"],
                delay_s,
            )
        )
    except HarnessStopped as exc:
        raise HarnessStopped(f"{item['id']}: {exc}") from exc
    return record


def budget_check(used: int, per_call: float, calls: int, limit: int) -> tuple[int, int, bool]:
    """(needed, remaining, fits) for one model's rolling 24-hour token budget."""
    needed = round(per_call * calls)
    remaining = limit - used
    return needed, remaining, needed <= remaining


async def tokens_used_24h(conn: asyncpg.Connection, model: str) -> int:
    used = await conn.fetchval(
        "SELECT coalesce(sum(prompt_tokens + completion_tokens), 0) FROM query_log "
        "WHERE model_used = $1 AND ts > now() - interval '24 hours'",
        model,
    )
    return int(used)


async def tokens_per_call(conn: asyncpg.Connection, model: str, purpose: str) -> float:
    avg = await conn.fetchval(
        "SELECT avg(prompt_tokens + completion_tokens) FROM query_log "
        "WHERE model_used = $1 AND purpose = $2 AND ts > now() - interval '7 days'",
        model,
        purpose,
    )
    return float(avg) if avg is not None else float(DEFAULT_TOKENS_PER_CALL[purpose])


def item_cost(
    item: dict[str, Any], gen_model: str, judge_model: str, cost: dict[str, float]
) -> dict[str, float]:
    """Estimated tokens one item spends per model, margin included: one generation, plus one judge call
    when the item is answerable."""
    need = {gen_model: cost["query"] * BUDGET_MARGIN}
    if item["type"] != "unanswerable":
        need[judge_model] = need.get(judge_model, 0.0) + cost["eval_judge"] * BUDGET_MARGIN
    return need


def affordable_items(
    todo: list[dict[str, Any]],
    remaining: dict[str, int],
    gen_model: str,
    judge_model: str,
    cost: dict[str, float],
) -> int:
    """How many items, in run order, fit in every model's remaining budget."""
    left = dict(remaining)
    for n, item in enumerate(todo):
        need = item_cost(item, gen_model, judge_model, cost)
        if any(left.get(m, 0) < v for m, v in need.items()):
            return n
        for m, v in need.items():
            left[m] -= round(v)
    return len(todo)


async def preflight(
    conn: asyncpg.Connection, limit: int, plan: dict[str, list[tuple[str, int]]]
) -> list[str]:
    """plan: model -> [(purpose, calls)]. Prints each model's 24h use and the run's estimated need.
    Returns the models whose budget the run would exceed. query_log only sees calls made by this
    stack, and cannot tell provider accounts apart, so treat the result as an estimate."""
    problems = []
    print(f"pre-flight: provider daily cap {limit:,} tokens per model (rolling 24 h, from query_log)")
    for model, uses in plan.items():
        used = await tokens_used_24h(conn, model)
        needed_total = 0
        for purpose, calls in uses:
            per_call = await tokens_per_call(conn, model, purpose)
            needed_total += round(per_call * calls)
            print(f"  {model}: {calls} {purpose} calls x ~{per_call:,.0f} tokens")
        _, remaining, fits = budget_check(int(used), needed_total, 1, limit)
        print(
            f"  {model}: used {int(used):,} in last 24 h, remaining {remaining:,}, "
            f"this run needs ~{needed_total:,} -> {'OK' if fits else 'WOULD EXCEED'}"
        )
        if not fits:
            problems.append(model)
    return problems


def write_baseline_section(label: str, result: dict[str, Any], baseline_file: Path) -> None:
    meta, agg = result["meta"], result["aggregate"]
    r, g = agg["retrieval"], agg["generation"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    lines = [
        f"## Golden set baseline — {label}",
        "",
        f"Full run of all {meta['n_items']} golden-set items, {meta['finished_utc']}, by "
        f'`uv run python eval/run_eval.py --baseline "{label}"`. '
        f"Results: `{baseline_file.relative_to(ROOT)}`.",
        "",
        f"- Generator: `{meta['generator_model']}` (tier `{meta['llm_tier']}`), "
        f"prompt `{meta['prompt_version']}`; judge: `{meta['judge_model']}` (tier `{meta['judge_tier']}`), "
        f"prompt `{meta['judge_prompt_version']}`",
        "- Retrieval: vector-only, ACL-filtered in SQL as each item's seeded `as_user`; "
        f"answers use top {meta['top_k']}; metrics at top {meta['retrieve_k']}",
        f"- Golden set hash `{meta['golden_hash']}`; corpus {meta['corpus_chunks']} chunks; "
        "commits "
        + ", ".join(f"`{c}`" for c in dict.fromkeys(meta.get("git_commits") or [meta["git_commit"]])),
        "",
        "| Retrieval (answerable items) | n | recall@5 | recall@6 | recall@10 | all-hops@10 | MRR "
        "| nDCG@10 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in ("all_answerable", "single_hop", "buried_fact", "multi_hop", "near_miss"):
        if name in r:
            m = r[name]
            lines.append(
                f"| {name} | {m['n']} | {pct(m['recall@5'])} | {pct(m['recall@6'])} | {pct(m['recall@10'])} "
                f"| {pct(m['all_hops@10'])} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |"
            )
    lines += [
        "",
        "| Generation | rate | count / n |",
        "|---|---|---|",
    ]
    for key, title in (
        ("correct_refusal_unanswerable", "Refused unanswerable (hallucination guard)"),
        ("false_refusal_answerable", "Refused answerable (false refusals; truncations excluded)"),
        ("truncated_generations", "Truncated at the completion limit (neither answered nor refused)"),
        ("faithful", "Faithful (judge, answered items)"),
        ("relevant", "Relevant (judge, answered items)"),
        ("citations_supported", "Citations supported (judge-v2, answered items)"),
        ("correct_answerable", "Correct (judge; refusals and truncations count as not correct)"),
        ("near_miss_pairs_both_correct", "Near-miss pairs with both answers correct"),
    ):
        v = g.get(key)
        if not v or not v["n"]:
            continue
        lines.append(f"| {title} | {pct(v['rate'])} | {v['count']} / {v['n']} |")
    lines += [
        "",
        f"Judge errors: {g['judge_errors']}. "
        f"Hallucinated on unanswerable: {g['hallucinated_on_unanswerable'] or 'none'}. "
        f"Refused answerable: {g['refused_answerable'] or 'none'}. "
        f"Truncated: {g.get('truncated_items') or 'none'}.",
        "",
    ]
    section = "\n".join(lines)
    heading = lines[0]
    text = EVAL_RESULTS_MD.read_text(encoding="utf-8")
    if heading in text:
        before, _, after = text.partition(heading)
        rest = after.split("\n## ", 1)
        text = before + section + ("\n## " + rest[1] if len(rest) > 1 else "")
    else:
        marker = "\n## Measurement notes"
        text = text.replace(marker, "\n" + section + marker, 1) if marker in text else text + "\n" + section
    EVAL_RESULTS_MD.write_text(text, encoding="utf-8")


def previous_result(mode: str, exclude: Path) -> dict[str, Any] | None:
    files = sorted(p for p in RESULTS_DIR.glob(f"*_{mode}.json") if p != exclude)
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def print_comparison(current: dict[str, Any], previous: dict[str, Any] | None) -> None:
    def rows(agg: dict[str, Any]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for group, m in agg["retrieval"].items():
            for k in ("recall@6", "recall@10", "mrr", "ndcg@10"):
                out[f"{group} {k}"] = m[k]
        for k, v in agg.get("generation", {}).items():
            if isinstance(v, dict):
                out[k] = v["rate"]
        return out

    cur = rows(current["aggregate"])
    prev = rows(previous["aggregate"]) if previous else {}
    label = f"previous ({previous['meta']['run_id']})" if previous else "previous (none)"
    print(f"\n{'metric':45s} {label:>30s} {'current':>10s} {'delta':>8s}")
    for k, v in cur.items():
        p = prev.get(k)
        delta = f"{v - p:+.3f}" if v is not None and p is not None else ""
        print(f"{k:45s} {_fmt(p):>30s} {_fmt(v):>10s} {delta:>8s}")
    if previous and previous["meta"]["golden_hash"] != current["meta"]["golden_hash"]:
        print("WARNING: golden set changed since the previous run; deltas are not comparable.")


Partial = tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]
# Settings a resumed run must share with the session that started it, or results are not comparable.
RESUME_MUST_MATCH = (
    "golden_hash",
    "llm_tier",
    "prompt_version",
    "judge_tier",
    "judge_model",
    "judge_prompt_version",
    "top_k",
    "retrieve_k",
)


def read_partial(path: Path) -> Partial:
    """(original meta, item records, session records). Session lines are {"session": {...}}."""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = lines[0]["meta"]
    records = [line for line in lines[1:] if "session" not in line]
    sessions = [line["session"] for line in lines[1:] if "session" in line]
    return meta, records, sessions


def finalize_meta(meta: dict[str, Any], sessions: list[dict[str, Any]], finished_utc: str) -> dict[str, Any]:
    """Keep the original start time; accumulate elapsed time and commits across all sessions."""
    out = dict(meta)
    out["sessions"] = sessions
    out["finished_utc"] = finished_utc
    out["elapsed_min"] = round(sum(s["elapsed_min"] for s in sessions), 1)
    out["git_commits"] = [s["git_commit"] for s in sessions]
    return out


async def run(
    args: argparse.Namespace,
    golden: list[dict[str, Any]],
    resumed: Partial | None,
    force_budget: bool = False,
) -> int:
    settings = get_settings()
    resume_records: list[dict[str, Any]] = []
    prior_sessions: list[dict[str, Any]] = []
    original_meta: dict[str, Any] | None = None
    if resumed:
        original_meta, resume_records, prior_sessions = resumed
        meta = original_meta
        args.subset, args.retrieval_only, args.baseline = (
            meta["subset"],
            meta["retrieval_only"],
            meta["baseline"],
        )
        if meta["golden_hash"] != golden_hash():
            raise SystemExit("golden set changed since this partial run started; start a new run")
        partial = Path(args.resume)
        run_id = meta["run_id"]
    if args.baseline and (args.subset or args.retrieval_only):
        raise SystemExit("--baseline requires a full run with judging (no --subset, no --retrieval-only)")
    mode = mode_name(args.subset, args.retrieval_only)
    items = select_subset(golden, args.subset) if args.subset else golden
    delay_s = (args.delay_ms if args.delay_ms is not None else settings.eval_request_delay_ms) / 1000
    if not args.resume:
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{mode}"
        partial = RESULTS_DIR / f"{run_id}.partial.jsonl"
    done = {r["id"] for r in resume_records}
    todo = [i for i in items if i["id"] not in done]
    calls = 0 if args.retrieval_only else len(todo) + sum(i["type"] != "unanswerable" for i in todo)
    print(
        f"run {run_id}: {len(items)} items ({len(todo)} to do), up to {calls} LLM calls, "
        f"about {calls * delay_s / 60:.0f} min at {delay_s:.0f}s pacing"
    )

    judge_llm = None
    if not args.retrieval_only:
        judge_settings = settings.model_copy(
            update={"llm_max_completion_tokens": settings.eval_judge_max_completion_tokens}
        )
        judge_llm = OpenAICompatibleLLM(judge_settings, settings.eval_judge_tier)

    app = create_app(settings)
    records = list(resume_records)
    started = time.time()
    stopped: str | None = None
    session_started = datetime.now(UTC).isoformat(timespec="seconds")
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        async with pool.acquire() as conn:
            await resolve_gold_uuids(conn, items)
            corpus_chunks = await conn.fetchval("SELECT count(*) FROM chunks")
            if judge_llm is not None:
                gen_model = settings.provider(settings.llm_tier).model_id
                plan: dict[str, list[tuple[str, int]]] = defaultdict(list)
                plan[gen_model].append(("query", len(todo)))
                plan[judge_llm.model_id].append(
                    ("eval_judge", sum(i["type"] != "unanswerable" for i in todo))
                )
                over = await preflight(conn, settings.llm_daily_token_limit, plan)
                judge_model = judge_llm.model_id
                cost = {
                    "query": await tokens_per_call(conn, gen_model, "query"),
                    "eval_judge": await tokens_per_call(conn, judge_model, "eval_judge"),
                }
                if over and force_budget:
                    print("pre-flight: --force-budget given; the run continues until the provider stops it")
                elif over:
                    remaining = {
                        m: settings.llm_daily_token_limit - await tokens_used_24h(conn, m)
                        for m in {gen_model, judge_model}
                    }
                    fit = affordable_items(todo, remaining, gen_model, judge_model, cost)
                    if fit == 0:
                        raise SystemExit(
                            "pre-flight: no item fits in today's remaining budget; wait for the window"
                        )
                    print(
                        f"pre-flight: day plan: {fit} of {len(todo)} items fit today's remaining budget "
                        f"(estimates x{BUDGET_MARGIN}); the run stops cleanly before the next item would "
                        "cross a cap, and --resume continues it"
                    )
        fresh_meta = {
            "run_id": run_id,
            "mode": mode,
            "subset": args.subset,
            "retrieval_only": args.retrieval_only,
            "baseline": args.baseline,
            "is_baseline_eligible": mode == "full",
            "n_items": len(items),
            "item_ids": [i["id"] for i in items],
            "golden_hash": golden_hash(),
            "corpus_chunks": corpus_chunks,
            "git_commit": git_commit(),
            "llm_tier": settings.llm_tier,
            "prompt_version": PROMPT_VERSION,
            "judge_tier": None if args.retrieval_only else settings.eval_judge_tier,
            "judge_model": judge_llm.model_id if judge_llm else None,
            "judge_prompt_version": None if args.retrieval_only else JUDGE_PROMPT_VERSION,
            "top_k": settings.retrieval_top_k,
            # Phase 4: answers may come from the semantic cache; recorded so no run is read without it.
            "cache_enabled": settings.cache_enabled,
            "cache_similarity_threshold": settings.cache_similarity_threshold
            if settings.cache_enabled
            else None,
            "retrieve_k": RETRIEVE_K,
            "delay_ms": int(delay_s * 1000),
            "started_utc": session_started,
        }
        if original_meta is not None:
            changed = [k for k in RESUME_MUST_MATCH if original_meta.get(k) != fresh_meta[k]]
            if changed:
                raise SystemExit(
                    f"cannot resume: {changed} differ from the original session; start a new run"
                )
            meta = original_meta
        else:
            meta = fresh_meta
        RESULTS_DIR.mkdir(exist_ok=True)
        if not args.resume:
            partial.write_text(json.dumps({"meta": meta}) + "\n", encoding="utf-8")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval", timeout=180) as client:
            for n, item in enumerate(todo, 1):
                if judge_llm is not None and not force_budget:
                    async with pool.acquire() as conn:
                        need = item_cost(item, gen_model, judge_model, cost)
                        short = [
                            m
                            for m, v in need.items()
                            if await tokens_used_24h(conn, m) + v > settings.llm_daily_token_limit
                        ]
                    if short:
                        stopped = f"budget: {item['id']} would cross today's cap for {short}"
                        break
                try:
                    record = await evaluate_item(item, client, pool, app.state, judge_llm, settings, delay_s)
                except HarnessStopped as exc:
                    stopped = str(exc)
                    break
                records.append(record)
                with partial.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                status = (
                    ""
                    if args.retrieval_only
                    else (
                        " refused"
                        if record.get("refused")
                        else f" judge={'error' if record.get('judge_error') else 'ok'}"
                    )
                )
                print(f"  [{n}/{len(todo)}] {item['id']} {item['type']}{status}", flush=True)
    if judge_llm:
        await judge_llm.aclose()

    session_finished = datetime.now(UTC).isoformat(timespec="seconds")
    session: dict[str, Any] = {
        "started_utc": session_started,
        "finished_utc": session_finished,
        "elapsed_min": round((time.time() - started) / 60, 1),
        "items_done": len(records) - len(resume_records),
        "git_commit": git_commit(),
        "stopped": stopped,
    }
    with partial.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"session": session}) + "\n")
    sessions = [*prior_sessions, session]

    if stopped:
        print(f"\nSTOPPED: {stopped}\n{len(records)}/{len(items)} items saved in {partial}")
        print(f"Resume with: uv run python eval/run_eval.py --resume {partial.relative_to(ROOT)}")
        return 2

    meta = finalize_meta(meta, sessions, session_finished)
    meta["generator_model"] = next((r["model"] for r in records if r.get("model")), None)
    result = {"meta": meta, "aggregate": aggregate(records), "records": records}
    out = RESULTS_DIR / f"{run_id}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.unlink()
    eligible = meta["is_baseline_eligible"]
    print(f"\nresults: {out.relative_to(ROOT)} (mode: {mode}; baseline-eligible: {eligible})")
    print_comparison(result, previous_result(mode, out))
    if args.baseline:
        BASELINES_DIR.mkdir(exist_ok=True)
        slug = args.baseline.lower().replace(" ", "-")
        baseline_file = BASELINES_DIR / f"{slug}.json"
        baseline_file.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        write_baseline_section(args.baseline, result, baseline_file)
        print(f"baseline '{args.baseline}' recorded in EVAL_RESULTS.md and {baseline_file.relative_to(ROOT)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--subset", type=int, choices=sorted(SUBSET_ALLOCATION), help="fixed stratified sample"
    )
    parser.add_argument("--retrieval-only", action="store_true", help="retrieval metrics only; no LLM calls")
    parser.add_argument("--baseline", metavar="LABEL", help='record a full run as a baseline, e.g. "Phase 2"')
    parser.add_argument("--delay-ms", type=int, help="override EVAL_REQUEST_DELAY_MS")
    parser.add_argument("--resume", metavar="PARTIAL", help="continue a stopped run from its .partial.jsonl")
    parser.add_argument(
        "--force-containers",
        action="store_true",
        help="run even while other projects' containers are up (the budget check still applies)",
    )
    parser.add_argument(
        "--force-budget",
        action="store_true",
        help="ignore the daily token budget: no day plan, no per-item stop (container check still applies)",
    )
    args = parser.parse_args()
    require_stack(strict=True, force_containers=args.force_containers)
    if args.resume:
        args.resume = str(Path(args.resume).resolve())  # printed later relative to ROOT
    resumed = read_partial(Path(args.resume)) if args.resume else None
    sys.exit(asyncio.run(run(args, load_golden(), resumed, force_budget=args.force_budget)))


if __name__ == "__main__":
    main()

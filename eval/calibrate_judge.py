"""Judge calibration with negative and positive controls (Phase 2 gate).

    uv run python eval/calibrate_judge.py --check   # verify the set's construction; no LLM calls
    uv run python eval/calibrate_judge.py           # verify, then judge all 20 items (paced)

eval/judge_calibration.jsonl holds 20 synthetic answers over real retrieved contexts (the top 6
of the Phase 2 baseline for a golden item), each with a known flaw:
- fabrication (5): a value absent from every context chunk; caught when faithful = false
- wrong_question (5): a true context fact answering a neighbouring question; caught when correct = false
- bad_citation (5): a true fact cited to a context chunk that lacks it; caught when faithful = false
- good (5): correct, faithful, correctly cited; passed when all three verdicts are true
Expected verdicts, catch rules and the fitness threshold were fixed before the judge was run.
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.llm.provider import OpenAICompatibleLLM
from gateway.rag import resolve_tenant
from judge import JUDGE_PROMPT_VERSION, Source
from run_eval import RESULTS_DIR, HarnessStopped, judge_and_log, preflight

EVAL_DIR = Path(__file__).resolve().parent
CALIBRATION = EVAL_DIR / "judge_calibration.jsonl"
# Fixed before the first calibration run: a judge catching fewer fabrications than this is not fit to
# measure Phases 4-5, and its prompt is tightened before proceeding.
FABRICATION_PASS_RATE = 0.8
CATEGORIES = ("fabrication", "wrong_question", "bad_citation", "good")


def load(path: Path = CALIBRATION) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def context_for(conn: asyncpg.Connection, item: dict[str, Any]) -> dict[str, tuple[str, str]]:
    rows = await conn.fetch(
        """
        SELECT d.slug || '#' || c.ordinal AS gid, d.title, c.content
        FROM chunks c JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id
        WHERE t.slug = $1 AND d.slug || '#' || c.ordinal = ANY($2::text[])
        """,
        item["tenant"],
        item["context_gids"],
    )
    return {r["gid"]: (r["title"], r["content"]) for r in rows}


def check_item(item: dict[str, Any], ctx: dict[str, tuple[str, str]]) -> list[str]:
    """Construction rules, re-verified against the current corpus."""
    if set(ctx) != set(item["context_gids"]):
        return [
            f"{item['id']}: context chunks missing from the corpus: {set(item['context_gids']) - set(ctx)}"
        ]
    labels = {f"S{n}": ctx[gid][1] for n, gid in enumerate(item["context_gids"], 1)}
    has = [label for label, text in labels.items() if item["check_text"] in text]
    cited = item["cited_label"]
    if f"[{cited}]" not in item["answer"]:
        return [f"{item['id']}: answer does not cite {cited}"]
    cat = item["category"]
    if cat == "fabrication" and has:
        return [f"{item['id']}: fabricated value {item['check_text']!r} is present in {has}"]
    if cat in ("wrong_question", "good") and cited not in has:
        return [f"{item['id']}: cited {cited} does not contain the fact"]
    if cat == "bad_citation" and (cited in has or not has):
        return [f"{item['id']}: bad_citation needs the fact elsewhere in context but not in {cited}"]
    return []


def caught(item: dict[str, Any], verdict: dict[str, Any]) -> bool:
    return all(verdict[k] == v for k, v in item["caught_if"].items())


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    summary: dict[str, Any] = {}
    for cat in CATEGORIES:
        rs = [r for r in by_cat[cat] if "verdict" in r]
        summary[cat] = {
            "n": len(rs),
            "caught": sum(r["caught"] for r in rs),
            "rate": round(sum(r["caught"] for r in rs) / len(rs), 4) if rs else None,
            "full_verdict_match": sum(r["full_match"] for r in rs),
            "misses": [r["id"] for r in rs if not r["caught"]],
        }
    fab = summary["fabrication"]["rate"]
    summary["judge_errors"] = [r["id"] for r in results if "judge_error" in r]
    summary["fabrication_pass_rate"] = FABRICATION_PASS_RATE
    summary["fit"] = fab is not None and fab >= FABRICATION_PASS_RATE and not summary["judge_errors"]
    return summary


async def run(check_only: bool) -> int:
    settings = get_settings()
    items = load()
    pool = await create_pool(settings.database_dsn)
    try:
        contexts: dict[str, dict[str, tuple[str, str]]] = {}
        problems: list[str] = []
        async with pool.acquire() as conn:
            for item in items:
                contexts[item["id"]] = await context_for(conn, item)
                problems += check_item(item, contexts[item["id"]])
        counts = {cat: sum(i["category"] == cat for i in items) for cat in CATEGORIES}
        print(f"{len(items)} calibration items: {counts}")
        if problems:
            print("construction problems:\n" + "\n".join(f"  - {p}" for p in problems))
            return 1
        print("construction verified against the current corpus")
        if check_only:
            return 0

        judge_settings = settings.model_copy(
            update={"llm_max_completion_tokens": settings.eval_judge_max_completion_tokens}
        )
        judge_llm = OpenAICompatibleLLM(judge_settings, settings.eval_judge_tier)
        async with pool.acquire() as conn:
            if await preflight(
                conn, settings.llm_daily_token_limit, {judge_llm.model_id: [("eval_judge", len(items))]}
            ):
                print("pre-flight: judge budget would be exceeded; not starting")
                return 1
        delay_s = settings.eval_request_delay_ms / 1000
        results = []
        try:
            for n, item in enumerate(items, 1):
                ctx = contexts[item["id"]]
                sources = [
                    Source(f"S{k}", ctx[g][0], ctx[g][1]) for k, g in enumerate(item["context_gids"], 1)
                ]
                async with pool.acquire() as conn:
                    tenant_id = await resolve_tenant(conn, item["tenant"])
                out = await judge_and_log(
                    pool,
                    tenant_id,
                    judge_llm,
                    item["question"],
                    item["reference_answer"],
                    sources,
                    item["answer"],
                    delay_s,
                )
                r: dict[str, Any] = {"id": item["id"], "category": item["category"], **out}
                if "judge" in out:
                    v = out["judge"]
                    r["verdict"] = {k: v[k] for k in ("faithful", "relevant", "correct")}
                    r["caught"] = caught(item, v)
                    r["full_match"] = r["verdict"] == item["expected"]
                print(
                    f"  [{n}/{len(items)}] {item['id']} {item['category']:15s} "
                    f"{r.get('verdict', 'JUDGE ERROR')} caught={r.get('caught')}",
                    flush=True,
                )
                results.append(r)
        except HarnessStopped as exc:
            print(f"STOPPED: {exc}")
            return 2
        finally:
            await judge_llm.aclose()
    finally:
        await pool.close()

    summary = summarise(results)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{stamp}_judge-calibration.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    meta = {
        "judge_model": judge_llm.model_id,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "finished_utc": stamp,
    }
    out_path.write_text(
        json.dumps({"meta": meta, "summary": summary, "results": results}, indent=1), encoding="utf-8"
    )
    print(f"\nresults: {out_path}")
    print(f"{'category':15s} {'caught':>8s} {'rate':>7s} {'full verdict match':>19s}  misses")
    for cat in CATEGORIES:
        s = summary[cat]
        rate = "n/a" if s["rate"] is None else f"{s['rate'] * 100:.0f}%"
        print(
            f"{cat:15s} {s['caught']:>3d}/{s['n']:<4d} {rate:>7s} "
            f"{s['full_verdict_match']:>12d}/{s['n']:<6d} {s['misses']}"
        )
    print(
        f"\njudge {judge_llm.model_id} ({JUDGE_PROMPT_VERSION}): "
        f"{'FIT' if summary['fit'] else 'NOT FIT'} (fabrication pass rate {FABRICATION_PASS_RATE:.0%})"
    )
    return 0 if summary["fit"] else 3


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="verify construction only; no LLM calls")
    sys.exit(asyncio.run(run(parser.parse_args().check)))


if __name__ == "__main__":
    main()

"""Judge calibration with negative and positive controls (Phase 2 gate).

    uv run python eval/calibrate_judge.py --check   # verify the set's construction; no LLM calls
    uv run python eval/calibrate_judge.py           # verify, then judge every item (paced)
    uv run python eval/calibrate_judge.py --set eval/judge_calibration.jsonl  # the 20-item v1 set

The default set, eval/judge_calibration_v2.jsonl, holds 40 synthetic answers over real retrieved
contexts (the top 6 of the Phase 2 baseline for a golden item), 10 per category, each with a known
flaw. Items c01-c20 are the judge-v1 set (same answers and contexts), now its regression test.
- fabrication: a value absent from every context chunk; caught when faithful = false
- wrong_question: a true context fact answering a neighbouring question; caught when correct = false
- bad_citation: a true fact cited to a chunk that lacks it; caught when citations_supported = false
  (judge-v2; in the v1 set the rule was faithful = false, which judge-v1 never produced)
- good: correct, faithful, correctly cited; passed when every expected verdict is true
Each item's expected verdicts and catch rule, and PASS_RATES below, were fixed before the run.
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
from judge import JUDGE_PROMPT_VERSION, VERDICT_FIELDS, Source
from run_eval import RESULTS_DIR, HarnessStopped, judge_and_log, preflight, require_stack

EVAL_DIR = Path(__file__).resolve().parent
CALIBRATION = EVAL_DIR / "judge_calibration_v2.jsonl"
# Fixed before the judge-v2 calibration run. Fabrication 80% is the user's fitness bar (judge-v1 was
# held to it alone); the same bar applies to the other negative controls, and at most 1 in 10 good
# answers may be rejected. A judge below any of these is not fit to measure Phases 3-5.
PASS_RATES = {"fabrication": 0.8, "wrong_question": 0.8, "bad_citation": 0.8, "good": 0.9}
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
    summary["judge_errors"] = [r["id"] for r in results if "judge_error" in r]
    summary["pass_rates"] = PASS_RATES
    summary["fit"] = not summary["judge_errors"] and all(
        summary[cat]["rate"] is not None and summary[cat]["rate"] >= rate for cat, rate in PASS_RATES.items()
    )
    return summary


def partial_path(path: Path) -> Path:
    return RESULTS_DIR / f"judge-calibration_{path.stem}.partial.jsonl"


def read_done(partial: Path, judge_model: str) -> dict[str, dict[str, Any]]:
    """Verdicts already paid for by this judge model and prompt version (a stopped run resumes)."""
    if not partial.exists():
        return {}
    done = {}
    for line in partial.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            same = (rec["_judge_model"], rec["_judge_prompt_version"]) == (judge_model, JUDGE_PROMPT_VERSION)
            if same and "verdict" in rec:
                done[rec["id"]] = {k: v for k, v in rec.items() if not k.startswith("_")}
    return done


async def run(check_only: bool, path: Path = CALIBRATION) -> int:
    settings = get_settings()
    items = load(path)
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
        partial = partial_path(path)
        done = read_done(partial, judge_llm.model_id)
        async with pool.acquire() as conn:
            if await preflight(
                conn,
                settings.llm_daily_token_limit,
                {judge_llm.model_id: [("eval_judge", len(items) - len(done))]},
            ):
                print("pre-flight: judge budget would be exceeded; not starting")
                return 1
        delay_s = settings.eval_request_delay_ms / 1000
        if done:
            print(f"resuming: {len(done)} verdicts already in {partial.name}; judging the rest")
        results = [done[i["id"]] for i in items if i["id"] in done]
        RESULTS_DIR.mkdir(exist_ok=True)
        try:
            for n, item in enumerate(items, 1):
                if item["id"] in done:
                    continue
                ctx = contexts[item["id"]]
                sources = [
                    Source(f"S{k}", ctx[g][0], ctx[g][1]) for k, g in enumerate(item["context_gids"], 1)
                ]
                async with pool.acquire() as conn:
                    tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", item["tenant"])
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
                    r["verdict"] = {k: v[k] for k in VERDICT_FIELDS}
                    r["caught"] = caught(item, v)
                    r["full_match"] = all(r["verdict"][k] == want for k, want in item["expected"].items())
                print(
                    f"  [{n}/{len(items)}] {item['id']} {item['category']:15s} "
                    f"{r.get('verdict', 'JUDGE ERROR')} caught={r.get('caught')}",
                    flush=True,
                )
                results.append(r)
                with partial.open("a", encoding="utf-8") as f:
                    tag = {"_judge_model": judge_llm.model_id, "_judge_prompt_version": JUDGE_PROMPT_VERSION}
                    f.write(json.dumps({**r, **tag}) + "\n")
        except HarnessStopped as exc:
            print(f"STOPPED: {exc}")
            return 2
        finally:
            await judge_llm.aclose()
    finally:
        await pool.close()

    order = {i["id"]: n for n, i in enumerate(items)}
    results.sort(key=lambda r: order[r["id"]])
    summary = summarise(results)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{stamp}_judge-calibration.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    meta = {
        "judge_model": judge_llm.model_id,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "calibration_set": path.name,
        "finished_utc": stamp,
    }
    out_path.write_text(
        json.dumps({"meta": meta, "summary": summary, "results": results}, indent=1), encoding="utf-8"
    )
    partial_path(path).unlink(missing_ok=True)
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
        f"{'FIT' if summary['fit'] else 'NOT FIT'} (pass rates {PASS_RATES})"
    )
    return 0 if summary["fit"] else 3


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="verify construction only; no LLM calls")
    parser.add_argument("--set", type=Path, default=CALIBRATION, help="calibration set (default: v2)")
    args = parser.parse_args()
    require_stack()
    sys.exit(asyncio.run(run(args.check, args.set)))


if __name__ == "__main__":
    main()

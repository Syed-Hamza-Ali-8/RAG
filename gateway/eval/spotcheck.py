"""Hand spot-check of the LLM judge (Phase 2 gate: agreement on 20 items, disagreement documented).

    uv run python eval/spotcheck.py --write eval/results/<run>.json   # make the labelling sheet
    uv run python eval/spotcheck.py --score eval/spotcheck/<run>.jsonl  # agreement once labelled

--write picks 20 judged items deterministically (hash of run id + item id) and writes
eval/spotcheck/<run>.jsonl (one item per line, human fields null) plus a readable .md with the
question, reference answer, model answer, the top-6 source texts the model saw, and the judge's
verdict. A human fills human.faithful / human.relevant / human.correct (true/false) in the
.jsonl. --score refuses to run while any human field is null.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from gateway.config import get_settings
from gateway.db import create_pool

EVAL_DIR = Path(__file__).resolve().parent
SPOTCHECK_DIR = EVAL_DIR / "spotcheck"
SAMPLE_SIZE = 20
DIMENSIONS = ("faithful", "relevant", "correct")


def pick(records: list[dict[str, Any]], run_id: str, size: int = SAMPLE_SIZE) -> list[dict[str, Any]]:
    judged = [r for r in records if r.get("judge")]
    if len(judged) < size:
        raise SystemExit(f"only {len(judged)} judged items in this run; need {size}")
    key = lambda r: hashlib.sha256(f"{run_id}:{r['id']}".encode()).hexdigest()  # noqa: E731
    return sorted(sorted(judged, key=key)[:size], key=lambda r: r["id"])


def score(items: list[dict[str, Any]]) -> dict[str, Any]:
    missing = [i["id"] for i in items for d in DIMENSIONS if not isinstance(i["human"][d], bool)]
    if missing:
        raise SystemExit(f"unlabelled human fields on: {sorted(set(missing))}")
    out: dict[str, Any] = {"n": len(items)}
    for d in DIMENSIONS:
        disagree = [i["id"] for i in items if i["human"][d] != i["judge"][d]]
        out[d] = {"agreement": round(1 - len(disagree) / len(items), 4), "disagreements": disagree}
    pairs = [(i["human"][d], i["judge"][d]) for i in items for d in DIMENSIONS]
    out["overall_disagreement_rate"] = round(sum(h != j for h, j in pairs) / len(pairs), 4)
    return out


async def fetch_sources(tenant: str, gids: list[str]) -> dict[str, tuple[str, str]]:
    settings = get_settings()
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.slug || '#' || c.ordinal AS gid, d.title, c.content
                FROM chunks c JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id
                WHERE t.slug = $1 AND d.slug || '#' || c.ordinal = ANY($2::text[])
                """,
                tenant,
                gids,
            )
    finally:
        await pool.close()
    return {r["gid"]: (r["title"], r["content"]) for r in rows}


async def build_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    run_id, top_k = result["meta"]["run_id"], result["meta"]["top_k"]
    items = []
    for r in pick(result["records"], run_id):
        top = r["retrieved"][:top_k]
        sources = await fetch_sources(r["tenant"], top)
        items.append(
            {
                "id": r["id"],
                "type": r["type"],
                "question": r["question"],
                "expected_answer": r["expected_answer"],
                "answer": r["answer"],
                "sources": [
                    {"label": f"S{n}", "gid": g, "title": sources[g][0], "content": sources[g][1]}
                    for n, g in enumerate(top, 1)
                ],
                "judge": {d: r["judge"][d] for d in DIMENSIONS} | {"reason": r["judge"]["reason"]},
                "human": {d: None for d in DIMENSIONS} | {"labelled_by": None, "notes": ""},
            }
        )
    return items


def write_sheet(results_path: Path) -> None:
    result = json.loads(results_path.read_text(encoding="utf-8"))
    run_id = result["meta"]["run_id"]
    items = asyncio.run(build_items(result))
    SPOTCHECK_DIR.mkdir(exist_ok=True)
    jsonl = SPOTCHECK_DIR / f"{run_id}.jsonl"
    jsonl.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    md = [f"# Judge spot-check — run {run_id}", "", f"Label the `human` fields in `{jsonl.name}`.", ""]
    for i in items:
        md += [
            f"## {i['id']} ({i['type']})",
            "",
            f"**Question:** {i['question']}",
            "",
            f"**Reference answer:** {i['expected_answer']}",
            "",
            f"**Model answer:** {i['answer']}",
            "",
            f"**Judge:** faithful={i['judge']['faithful']} relevant={i['judge']['relevant']} "
            f"correct={i['judge']['correct']} — {i['judge']['reason']}",
            "",
            "<details><summary>Sources</summary>",
            "",
        ]
        md += [f"**[{s['label']}] {s['title']}** (`{s['gid']}`)\n\n{s['content']}\n" for s in i["sources"]]
        md += ["</details>", ""]
    (SPOTCHECK_DIR / f"{run_id}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {jsonl} and {jsonl.with_suffix('.md')} ({len(items)} items)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", metavar="RESULTS_JSON")
    group.add_argument("--score", metavar="SHEET_JSONL")
    args = parser.parse_args()
    if args.write:
        write_sheet(Path(args.write))
        return
    items = [
        json.loads(line) for line in Path(args.score).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    print(json.dumps(score(items), indent=1))
    sys.exit(0)


if __name__ == "__main__":
    main()

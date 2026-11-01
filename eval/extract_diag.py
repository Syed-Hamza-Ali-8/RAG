"""One diagnostic extraction call (EVAL_RESULTS.md, M2 probe deviation):
where did the 2,000 completion tokens go?

    uv run python eval/extract_diag.py --tenant acme \
        --chunk eng-postmortem-2026-03-atlas-outage#0 --limit 8000

Same model, prompt (extract-v1) and temperature as the probe, with a larger completion limit. Prints the
provider's usage object verbatim (including any reasoning-token breakdown) and the sizes of the reasoning and
content fields. Nothing is stored in the graph; the call is logged in graph_extraction under prompt_version
'extract-v1-diag' so its tokens count against the daily budget.
"""

import argparse
import asyncio
import json
import time

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.graph.extract import build_messages, parse
from gateway.llm.provider import get_client
from run_eval import BUDGET_MARGIN, tokens_used_24h


async def main(tenant: str, chunk: str, limit: int) -> None:
    s = get_settings()
    client, model = get_client(s, s.extraction_tier)
    pool = await create_pool(s.database_dsn)
    slug, ordinal = chunk.rsplit("#", 1)
    try:
        async with pool.acquire() as conn:
            c = await conn.fetchrow(
                "SELECT c.id, c.tenant_id, c.heading_path, c.content FROM chunks c "
                "JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id "
                "WHERE t.slug = $1 AND d.slug = $2 AND c.ordinal = $3",
                tenant,
                slug,
                int(ordinal),
            )
            if c is None:
                raise SystemExit(f"{tenant}/{chunk} is not in the corpus")
            used = await tokens_used_24h(conn, model)
        if used + limit * BUDGET_MARGIN > s.llm_daily_token_limit:
            raise SystemExit(f"STOPPED (budget): {model} at {used:,} tokens")
        started = time.perf_counter()
        r = await client.chat.completions.create(
            model=model,
            messages=build_messages(c["heading_path"], c["content"]),
            temperature=s.llm_temperature,
            max_completion_tokens=limit,
        )
        ms = round((time.perf_counter() - started) * 1000)
        choice, usage = r.choices[0], r.usage
        msg = choice.message.model_dump()
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning") or ""
        print(f"model {r.model}; finish_reason {choice.finish_reason}; {ms} ms")
        print("usage:", json.dumps(usage.model_dump() if usage else None))
        print(f"reasoning field: {len(reasoning):,} chars; content field: {len(content):,} chars")
        try:
            ex = parse(content)
            print(f"content parses: {len(ex.entities)} entities, {len(ex.relations)} relations")
        except ValueError as exc:
            print(f"content does not parse: {exc}")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO graph_extraction (tenant_id, chunk_id, model_used, prompt_version, "
                "prompt_tokens, completion_tokens, llm_ms, outcome, entities, relations, error) "
                "VALUES ($1, $2, $3, 'extract-v1-diag', $4, $5, $6, $7, 0, 0, $8)",
                c["tenant_id"],
                c["id"],
                r.model or model,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
                ms,
                "truncated" if choice.finish_reason == "length" else "ok",
                f"diagnostic, limit {limit}; not stored",
            )
    finally:
        await client.close()
        await pool.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--chunk", required=True)
    ap.add_argument("--limit", type=int, default=8000)
    a = ap.parse_args()
    asyncio.run(main(a.tenant, a.chunk, a.limit))

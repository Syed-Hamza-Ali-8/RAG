"""M2 diagnosis (EVAL_RESULTS.md, M2 full corpus): are the hops M1 misses reachable by the graph walk, and
where would they rank in the graph list under its pre-registered order (depth, support) versus cosine?

    uv run python eval/phase5/graph_reach.py

Read-only; no LLM calls. Output committed as eval/phase5/m2_graph_reach.txt.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "eval")

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.retrieval.graph import graph_search
from gateway.retrieval.hybrid import HybridConfig, hybrid_search
from gateway.retrieval.vector import RetrievedChunk


def gid(c: RetrievedChunk) -> str:
    return f"{c.document_slug}#{c.ordinal}"


async def main(items: list[dict[str, Any]], m1: dict[str, dict[str, Any]]) -> None:
    s = get_settings()
    emb = await asyncio.to_thread(Embedder, s.embedding_model_id, s.embedding_dim, s.embedding_cache_dir)
    pool = await create_pool(s.database_dsn)
    out: list[tuple[str, str, int, int | None, int | None]] = []
    try:
        async with pool.acquire() as conn:
            for it in (i for i in items if i["type"] == "multi_hop"):
                auth = await auth_for_email(conn, it["tenant"], it["as_user"])
                vec = await emb.embed_query(it["question"])
                fused = await hybrid_search(
                    conn,
                    acl_filter=auth.acl(),
                    question=it["question"],
                    query_embedding=vec,
                    top_k=20,
                    config=HybridConfig(),
                )
                walked = await graph_search(
                    conn,
                    acl_filter=auth.acl(),
                    seed_chunk_ids=[c.chunk_id for c in fused[:6]],
                    query_embedding=vec,
                    max_depth=2,
                    top_k=10_000,
                )
                by_order = [gid(c) for c in walked]
                by_cos = [gid(c) for c in sorted(walked, key=lambda c: -c.score)]
                for g in (g for g in it["gold_chunk_ids"] if g not in m1[it["id"]]["retrieved"][:6]):
                    out.append(
                        (
                            it["id"],
                            g,
                            len(by_order),
                            by_order.index(g) + 1 if g in by_order else None,
                            by_cos.index(g) + 1 if g in by_cos else None,
                        )
                    )
    finally:
        await pool.close()
    print("item gold_hop graph_list_size rank_depth_support rank_cosine")
    for o in out:
        print(*o)
    reach = [o for o in out if o[3] is not None and o[4] is not None]
    print(f"missing-from-M1-top6 hops: {len(out)}; in graph list at all: {len(reach)}")
    print(f"in graph top 20, depth/support order: {sum(o[3] <= 20 for o in reach if o[3])}")
    print(f"in graph top 20, cosine order: {sum(o[4] <= 20 for o in reach if o[4])}")
    print(f"in graph top 6, cosine order: {sum(o[4] <= 6 for o in reach if o[4])}")
    print("median graph list size:", sorted(o[2] for o in out)[len(out) // 2])


if __name__ == "__main__":
    golden = [json.loads(line) for line in Path("eval/golden_set.jsonl").read_text().splitlines() if line]
    m1_records = json.loads(Path("eval/phase5/m1_hybrid.json").read_text())["records"]
    asyncio.run(main(golden, {r["id"]: r for r in m1_records}))

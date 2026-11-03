"""M2 option A ceiling (EVAL_RESULTS.md, option A pre-registration): for each multi-hop gold hop missing
from M1's top 6, its fused score with a cosine-ordered graph vote, against the score of M1's sixth chunk.
Optimistic: assumes the chunks already in the top 6 gain nothing from the graph list.

    uv run python eval/phase5/graph_ceiling.py

Read-only; no LLM calls. Output committed as eval/phase5/m2_graph_ceiling.txt.
"""

import asyncio
import json
from pathlib import Path

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.retrieval.graph import graph_search
from gateway.retrieval.hybrid import HybridConfig, hybrid_search
from gateway.retrieval.keyword import keyword_search
from gateway.retrieval.vector import RetrievedChunk, vector_search

K = 60


def gid(c: RetrievedChunk) -> str:
    return f"{c.document_slug}#{c.ordinal}"


def rrf_score(g: str, lists: tuple[list[str], ...]) -> float:
    return sum(1 / (K + lst.index(g) + 1) for lst in lists if g in lst)


async def main(items: list[dict], m1: dict[str, dict]) -> None:
    s = get_settings()
    emb = await asyncio.to_thread(Embedder, s.embedding_model_id, s.embedding_dim, s.embedding_cache_dir)
    pool = await create_pool(s.database_dsn)
    try:
        async with pool.acquire() as conn:
            for it in (i for i in items if i["type"] == "multi_hop"):
                missing = [g for g in it["gold_chunk_ids"] if g not in m1[it["id"]]["retrieved"][:6]]
                if not missing:
                    continue
                acl_filter = (await auth_for_email(conn, it["tenant"], it["as_user"])).acl()
                vec = await emb.embed_query(it["question"])
                vs = await vector_search(conn, acl_filter=acl_filter, query_embedding=vec, top_k=20)
                v = [gid(c) for c in vs]
                kw = await keyword_search(
                    conn, acl_filter=acl_filter, question=it["question"], query_embedding=vec, top_k=20
                )
                k = [gid(c) for c in kw]
                fused = await hybrid_search(
                    conn,
                    acl_filter=acl_filter,
                    question=it["question"],
                    query_embedding=vec,
                    top_k=20,
                    config=HybridConfig(),
                )
                sixth = rrf_score(gid(fused[5]), (v, k))
                walked = await graph_search(
                    conn,
                    acl_filter=acl_filter,
                    seed_chunk_ids=[c.chunk_id for c in fused[:6]],
                    query_embedding=vec,
                    max_depth=2,
                    top_k=10_000,
                )
                by_cos = [gid(c) for c in sorted(walked, key=lambda c: -c.score)][:20]
                for g in missing:
                    gr = by_cos.index(g) + 1 if g in by_cos else None
                    base = rrf_score(g, (v, k))
                    best = base + (1 / (K + gr) if gr else 0)
                    print(
                        it["id"],
                        g,
                        "vec",
                        v.index(g) + 1 if g in v else None,
                        "kw",
                        k.index(g) + 1 if g in k else None,
                        "graph_cos",
                        gr,
                        f"M1 {base:.4f} +graph {best:.4f} vs M1 6th {sixth:.4f}",
                        "CAN_CLIMB" if best > sixth else "",
                    )
    finally:
        await pool.close()


if __name__ == "__main__":
    golden = [json.loads(line) for line in Path("eval/golden_set.jsonl").read_text().splitlines() if line]
    m1_records = json.loads(Path("eval/phase5/m1_hybrid.json").read_text())["records"]
    asyncio.run(main(golden, {r["id"]: r for r in m1_records}))

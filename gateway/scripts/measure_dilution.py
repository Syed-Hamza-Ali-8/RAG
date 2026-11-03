"""Measure how much merging dilutes a section's retrieval score (Phase 5 success criterion).

    uv run python scripts/measure_dilution.py --tenant acme \\
        --question "What is the on-call allowance per week?" \\
        --document eng-runbook-on-call --section "Allowance and Time Off"

Compares, for one question:
- ISOLATED: the named section embedded on its own, in the same form it has inside its merged
  chunk (the chunk's heading path as prefix, the section heading inline, then its text);
- MERGED: the stored chunk that contains the section, its score and its rank among all of the
  tenant's chunks (exactly what /v1/query's vector search sees);
- the top-k cutoff score, i.e. what the merged chunk would have needed to be retrieved.
No LLM calls are made.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.ingest.chunker import HEADING_SEP, build_embed_text
from gateway.ingest.embedder import Embedder
from gateway.ingest.loaders import load_document
from gateway.rag import resolve_tenant


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    top_k = args.top_k or settings.retrieval_top_k
    embedder = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            tenant_id = await resolve_tenant(conn, args.tenant)
            source_uri = await conn.fetchval(
                "SELECT source_uri FROM documents WHERE tenant_id = $1 AND slug = $2",
                tenant_id,
                args.document,
            )
            if source_uri is None:
                sys.exit(f"no document {args.document!r} for tenant {args.tenant!r}")

            sections = [
                s for s in load_document(Path(source_uri)).sections if s.heading_path[-1:] == (args.section,)
            ]
            if len(sections) != 1:
                sys.exit(f"expected exactly one section headed {args.section!r}, found {len(sections)}")
            section = sections[0]

            query_vec = await embedder.embed_query(args.question)
            ranked = await conn.fetch(
                """
                SELECT rank, ordinal, heading_path, token_count, content, score FROM (
                    SELECT row_number() OVER (ORDER BY c.embedding <=> $2) AS rank,
                           d.slug, c.ordinal, c.heading_path, c.token_count, c.content,
                           1 - (c.embedding <=> $2) AS score
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                    WHERE c.tenant_id = $1
                ) r
                WHERE slug = $3 OR rank = $4
                ORDER BY rank
                """,
                tenant_id,
                query_vec,
                args.document,
                top_k,
            )
            total = await conn.fetchval("SELECT count(*) FROM chunks WHERE tenant_id = $1", tenant_id)
    finally:
        await pool.close()

    cutoff = next(r for r in ranked if r["rank"] == top_k)
    first_sentence = section.text.split(". ")[0]
    holders = [r for r in ranked if first_sentence in r["content"]]
    if not holders:
        sys.exit("no stored chunk of the document contains the section text; re-seed the corpus")
    merged = holders[0]

    # The section's form inside its merged chunk: the chunk's heading path as prefix, and the
    # section's heading (relative to that path) inline above its text.
    prefix = tuple(merged["heading_path"].split(HEADING_SEP)) if merged["heading_path"] else ()
    inline = HEADING_SEP.join(section.heading_path[len(prefix) :])
    isolated_text = build_embed_text(
        merged["heading_path"], f"{inline}\n\n{section.text}" if inline else section.text
    )
    (isolated_vec,) = await embedder.embed_passages([isolated_text])
    isolated = float(np.dot(np.asarray(query_vec), np.asarray(isolated_vec)))  # unit vectors: dot = cosine

    print(f"Q [{args.tenant}]: {args.question}")
    print(
        f"Section: {args.document} > {args.section} "
        f"({embedder.count_tokens(isolated_text)} tokens embedded alone)"
    )
    print(f"  ISOLATED  score {isolated:.4f}  (above the top-{top_k} cutoff: {isolated > cutoff['score']})")
    print(
        f"  MERGED    score {merged['score']:.4f}  rank {merged['rank']} of {total}  "
        f"chunk #{merged['ordinal']} ({merged['token_count']} tokens) "
        f"{'retrieved' if merged['rank'] <= top_k else 'MISSED'}"
    )
    print(f"  top-{top_k} cutoff score {cutoff['score']:.4f}")
    print(f"  dilution: {isolated - merged['score']:+.4f} lost by merging")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--document", required=True, help="document slug, e.g. eng-runbook-on-call")
    parser.add_argument("--section", required=True, help="exact heading text of the section to isolate")
    parser.add_argument("--top-k", type=int)
    asyncio.run(main(parser.parse_args()))

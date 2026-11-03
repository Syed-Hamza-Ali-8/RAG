"""Diagnose a refused (or wrong) answer: was it the retriever, the model or the citation check?

    uv run python scripts/diagnose_refusals.py --tenant acme --as-user engineer@acme.example \\
        --question "What is the on-call allowance per week?" \\
        [--log-id 94] [--needle "PKR 15,000"] [--llm]

Prints:
- the top-k retrieved chunks with similarity scores (the exact retrieval path /v1/query uses);
- with --log-id: the stored query_log row (answer_raw, citation verdict, prompt_version);
- with --needle: where every chunk containing that text ranks among the tenant's chunks,
  i.e. whether the answer exists in the corpus and how far retrieval missed it;
- with --llm: one live LLM call on the same prompt, the raw output and the citation check.

query_log does not store question text, so the question is passed explicitly.
"""

import argparse
import asyncio

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.deps import auth_for_email
from gateway.ingest.embedder import Embedder
from gateway.llm.prompts import PROMPT_VERSION, build_messages
from gateway.llm.provider import OpenAICompatibleLLM
from gateway.retrieval.vector import vector_search
from gateway.security.guardrails import check_citations


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    embedder = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    top_k = args.top_k or settings.retrieval_top_k
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            auth = await auth_for_email(conn, args.tenant, args.as_user)
            tenant_id = auth.tenant_id
            query_vec = await embedder.embed_query(args.question)
            chunks = await vector_search(conn, acl_filter=auth.acl(), query_embedding=query_vec, top_k=top_k)
            total = await conn.fetchval("SELECT count(*) FROM chunks WHERE tenant_id = $1", tenant_id)

            print(
                f"Q [{args.tenant} as {args.as_user}, roles {list(auth.roles)}, "
                f"clearance {auth.clearance}]: {args.question}"
            )
            print(f"\nTop {top_k} of {total} chunks:")
            for n, c in enumerate(chunks, 1):
                print(f"  S{n}  {c.score:.4f}  {c.document_slug}#{c.ordinal}  [{c.heading_path}]")

            if args.log_id is not None:
                row = await conn.fetchrow(
                    "SELECT refused, prompt_version, citations_valid, citations_rejected, answer_raw "
                    "FROM query_log WHERE id = $1 AND tenant_id = $2",
                    args.log_id,
                    tenant_id,
                )
                print(f"\nquery_log id {args.log_id}:")
                if row is None:
                    print("  not found for this tenant")
                else:
                    print(
                        f"  refused={row['refused']} prompt_version={row['prompt_version']} "
                        f"citations_valid={row['citations_valid']} "
                        f"citations_rejected={row['citations_rejected']}"
                    )
                    print(f"  answer_raw: {row['answer_raw']!r}")

            if args.needle:
                hits = await conn.fetch(
                    """
                    SELECT rank, slug, ordinal, heading_path, score FROM (
                        SELECT row_number() OVER (ORDER BY c.embedding <=> $2) AS rank,
                               d.slug, c.ordinal, c.heading_path, c.content,
                               1 - (c.embedding <=> $2) AS score
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                        WHERE c.tenant_id = $1
                    ) ranked
                    WHERE position($3 IN content) > 0
                    ORDER BY rank
                    """,
                    tenant_id,
                    query_vec,
                    args.needle,
                )
                # Which chunks this user may read, decided by the real SQL predicate (not re-implemented).
                readable = {
                    f"{c.document_slug}#{c.ordinal}"
                    for c in await vector_search(
                        conn, acl_filter=auth.acl(), query_embedding=query_vec, top_k=total
                    )
                }
                print(f"\nChunks containing {args.needle!r} (ranked tenant-wide, without the ACL filter):")
                if not hits:
                    print("  none: the answer text is not in this tenant's corpus")
                for h in hits:
                    gid_ = f"{h['slug']}#{h['ordinal']}"
                    if gid_ not in readable:
                        marker = "NOT READABLE by this user (ACL)"
                    else:
                        marker = (
                            "retrieved"
                            if gid_ in {f"{c.document_slug}#{c.ordinal}" for c in chunks}
                            else "MISSED"
                        )
                    print(
                        f"  rank {h['rank']:3d}/{total}  {h['score']:.4f}  "
                        f"{h['slug']}#{h['ordinal']}  [{h['heading_path']}]  {marker}"
                    )
    finally:
        await pool.close()

    if args.llm:
        if not chunks:
            print("\nNo chunks retrieved; /v1/query would refuse without an LLM call.")
            return
        llm = OpenAICompatibleLLM(settings, settings.llm_tier)
        try:
            out = await llm.complete(build_messages(args.question, chunks))
        finally:
            await llm.aclose()
        check = check_citations(out.text, len(chunks))
        print(f"\nLive LLM ({out.model}, prompt {PROMPT_VERSION}):")
        print(f"  raw: {out.text!r}")
        print(
            f"  citation check: grounded={check.grounded} valid={[f'S{i + 1}' for i in check.valid_indices]} "
            f"rejected={check.invalid_labels}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--as-user", required=True, help="seeded user email; retrieval runs with their ACL")
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--log-id", type=int, help="query_log id of the original request")
    parser.add_argument("--needle", help="text the correct answer contains, e.g. 'PKR 15,000'")
    parser.add_argument("--llm", action="store_true", help="make one live LLM call (uses free-tier quota)")
    asyncio.run(main(parser.parse_args()))

"""Postgres full-text keyword search with the ACL predicate in the SQL WHERE clause (invariant 1).

Configuration fixed by the Phase 5 pre-registration (EVAL_RESULTS.md): the `english` config over heading
path and content (migration 011); the query is the OR of the question's lexemes, since an AND of every word
would match almost nothing for a full-sentence question; ranked by ts_rank_cd with no length normalisation.
Each hit also carries its cosine similarity to the query embedding, so callers that read RetrievedChunk.score
(the routing classifier) see cosines whichever path found the chunk.
"""

import asyncpg

from gateway.retrieval.vector import RetrievedChunk
from gateway.security import acl


def _keyword_sql() -> str:
    # $1 question text, $2 query embedding, $3 limit, $4-$6 ACL. Composed per call from constants (see
    # gateway.security.acl) so the isolation suite can remove the predicate and prove its probes then fail.
    return (
        "SELECT c.id, c.document_id, d.slug, d.title, c.ordinal, c.heading_path, c.content, "
        "1 - (c.embedding <=> $2) AS score "
        "FROM chunks c JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id, "
        "to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector('english', $1)), ' | ')) q "
        "WHERE " + acl.acl_predicate("c", 4) + " AND c.content_tsv @@ q "
        "ORDER BY ts_rank_cd(c.content_tsv, q) DESC, c.id LIMIT $3"
    )


async def keyword_search(
    conn: asyncpg.Connection,
    *,
    acl_filter: acl.AclFilter,
    question: str,
    query_embedding: list[float],
    top_k: int,
) -> list[RetrievedChunk]:
    rows = await conn.fetch(_keyword_sql(), question, query_embedding, top_k, *acl_filter.params())
    return [
        RetrievedChunk(
            chunk_id=r["id"],
            document_id=r["document_id"],
            document_slug=r["slug"],
            document_title=r["title"],
            ordinal=r["ordinal"],
            heading_path=r["heading_path"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]

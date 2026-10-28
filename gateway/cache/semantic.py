"""Tenant- and permission-scoped semantic cache (migration 003; spec 4.2; CLAUDE.md invariant 4).

A stored answer is served only when ALL of these hold, in the SQL WHERE clause:
- same tenant_id and same role_signature (sha256 of sorted roles + clearance, from the database at query
  time), so two users whose permissions differ never share an entry;
- same content_key (the question's content words), the near-miss defence: embeddings alone cannot keep
  near-miss questions apart on this corpus (EVAL_RESULTS.md, Phase 4 finding);
- cosine similarity >= the configured threshold, a second filter below the word check;
- not expired.
Only answered outcomes are stored. Questions matching the bypass list are neither served nor stored.
Invalidation (correction K) is done by triggers in migration 003, so no write path can skip it.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from gateway.models.query import Citation

# Words that do not change what is being asked. Question words, negations and comparatives (below,
# least, more, before ...) are deliberately kept: they change the answer.
STOPWORDS = frozenset(
    "a an the is are was were be been being am do does did of in on at to for from by with and or as it its "
    "this that these those there please can could would should will shall may might me my our we us i you "
    "your their they them has have had".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def role_signature(roles: tuple[str, ...] | list[str], clearance: int) -> str:
    """sha256 of the sorted, de-duplicated roles plus the clearance (spec 4.2)."""
    return hashlib.sha256(json.dumps([sorted(set(roles)), clearance]).encode()).hexdigest()


def content_key(question: str) -> str:
    """The question's content words, sorted: equal for case, punctuation, stopword and order changes;
    different whenever a content word or number differs (99.9% vs 99.0%, maternity vs paternity)."""
    text = question.lower().replace(chr(0x2019), "'").replace("'s", "")  # curly apostrophe
    return " ".join(sorted({t for t in _TOKEN.findall(text) if t not in STOPWORDS}))


@dataclass(frozen=True)
class CacheConfig:
    threshold: float
    ttl_hours: int
    bypass_patterns: tuple[re.Pattern[str], ...]

    @classmethod
    def from_patterns(cls, threshold: float, ttl_hours: int, patterns: list[str]) -> "CacheConfig":
        return cls(threshold, ttl_hours, tuple(re.compile(p, re.IGNORECASE) for p in patterns))

    def bypassed(self, question: str) -> bool:
        return any(p.search(question) for p in self.bypass_patterns)


@dataclass(frozen=True)
class CachedAnswer:
    entry_id: UUID
    answer: str
    citations: list[Citation]
    model_used: str
    similarity: float


def _scope_predicate() -> str:
    # The permission scope of every lookup. $1 tenant_id, $2 role_signature. Composed per call so the
    # isolation suite can remove a component and prove its probes then fail.
    return "c.tenant_id = $1 AND c.role_signature = $2"


def _lookup_sql() -> str:
    # $3 content_key, $4 query embedding, $5 similarity threshold.
    return (
        "SELECT c.id, c.answer, c.citations, c.model_used, 1 - (c.query_embedding <=> $4) AS similarity "
        "FROM semantic_cache c WHERE " + _scope_predicate() + " AND c.content_key = $3 "
        "AND c.expires_at > now() AND 1 - (c.query_embedding <=> $4) >= $5 "
        "ORDER BY c.query_embedding <=> $4 LIMIT 1"
    )


async def lookup(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    signature: str,
    key: str,
    embedding: list[float],
    threshold: float,
) -> CachedAnswer | None:
    row = await conn.fetchrow(_lookup_sql(), tenant_id, signature, key, embedding, threshold)
    if row is None:
        return None
    await conn.execute("UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE id = $1", row["id"])
    return CachedAnswer(
        entry_id=row["id"],
        answer=row["answer"],
        citations=[Citation(**c) for c in json.loads(row["citations"])],
        model_used=row["model_used"],
        similarity=float(row["similarity"]),
    )


async def store(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    signature: str,
    key: str,
    question: str,
    embedding: list[float],
    answer: str,
    citations: list[Citation],
    model_used: str,
    ttl_hours: int,
) -> None:
    """Store an answered outcome. Callers never pass refusals or truncations (C8)."""
    if not citations:
        raise ValueError("only answered outcomes with citations are cached")
    await conn.execute(
        """
        INSERT INTO semantic_cache (tenant_id, role_signature, content_key, query_text, query_embedding,
                                    answer, citations, model_used, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
        """,
        tenant_id,
        signature,
        key,
        question,
        embedding,
        answer,
        json.dumps([c.model_dump(mode="json") for c in citations]),
        model_used,
        datetime.now(UTC) + timedelta(hours=ttl_hours),
    )


async def discard(conn: asyncpg.Connection, entry_id: UUID) -> None:
    await conn.execute("DELETE FROM semantic_cache WHERE id = $1", entry_id)

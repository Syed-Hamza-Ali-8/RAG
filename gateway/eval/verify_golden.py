"""Verify the golden set against the current corpus (CLAUDE.md correction F; Phase 2).

    uv run python eval/verify_golden.py            # verify; exit 1 on any problem
    uv run python eval/verify_golden.py --resolve  # (re)compute gold ids from evidence, then verify
    uv run python eval/verify_golden.py --write-review  # also regenerate eval/golden_set_review.md

Every answerable item carries evidence: verbatim text copied from the corpus, one entry per
hop. Each item runs as a real seeded user (as_user, from corpus/tenants.json); as_role and
as_clearance must equal that user's roles and clearance. Gold chunk ids
("document_slug#chunk_ordinal") are the chunks that contain the evidence AND that the user may
read under the chunk ACLs, so the gold set stays correct once Phase 3 enforces ACLs. Checks:
- composition: 50 single_hop, 25 multi_hop, 15 unanswerable, 10 near_miss (5 complete pairs);
  exactly 20 buried_fact items, all single_hop; should_refuse exactly for unanswerable items;
- buried_fact_paraphrase items reword a buried_fact item (paraphrase_of) and are not counted
  in the 20;
- every gold id resolves to an existing chunk, and the stored ids equal the ids recomputed
  from the evidence (catches stale ids after a re-seed or corpus edit);
- every evidence entry resolves to >= 1 permitted chunk; multi_hop hops span >= 2 chunks;
- unanswerable items: none of absent_terms occurs (case-insensitive, whole word) anywhere
  in the tenant's corpus, regardless of role;
- buried_fact (and paraphrase) items, the structural selection rule: every gold chunk has
  >= 300 tokens and the single evidence sentence is <= 6.5% (~6%) of its tokens. Selection never looks
  at retrieval rank; the vector-only rank is reported for information only.
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.ingest.embedder import Embedder

GOLDEN = Path(__file__).resolve().parent / "golden_set.jsonl"
REVIEW = Path(__file__).resolve().parent / "golden_set_review.md"
TENANTS = Path(__file__).resolve().parent.parent / "corpus" / "tenants.json"
COMPOSITION = {"single_hop": 50, "multi_hop": 25, "unanswerable": 15, "near_miss": 10}
BURIED = 20
BURIED_TAGS = ("buried_fact", "buried_fact_paraphrase")
BURIED_MIN_CHUNK_TOKENS = 300
BURIED_MAX_EVIDENCE_SHARE = 0.065  # "under ~6%"; set to 6.5% so the original ten items at 6.1% pass


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_structure(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        errors.append("duplicate ids")
    counts = Counter(i["type"] for i in items)
    if dict(counts) != COMPOSITION:
        errors.append(f"composition {dict(counts)} != {COMPOSITION}")
    buried = [i for i in items if "buried_fact" in i["tags"]]
    if len(buried) != BURIED:
        errors.append(f"{len(buried)} buried_fact items (need exactly {BURIED})")
    buried_ids = {i["id"] for i in buried}
    for i in items:
        if any(tag in i["tags"] for tag in BURIED_TAGS) and i["type"] != "single_hop":
            errors.append(f"{i['id']}: buried items must be single_hop")
        if "buried_fact_paraphrase" in i["tags"] and i.get("paraphrase_of") not in buried_ids:
            errors.append(f"{i['id']}: paraphrase_of must name a buried_fact item")
    users = {
        (t["slug"], u["email"]): u
        for t in json.loads(TENANTS.read_text(encoding="utf-8"))["tenants"]
        for u in t["users"]
    }
    for i in items:
        user = users.get((i["tenant"], i.get("as_user")))
        if user is None:
            errors.append(f"{i['id']}: as_user {i.get('as_user')!r} is not a seeded {i['tenant']} user")
        elif sorted(user["roles"]) != sorted(i["as_role"]) or user["clearance"] != i["as_clearance"]:
            errors.append(f"{i['id']}: as_role/as_clearance do not match seeded user {i['as_user']}")
    for i in items:
        if i["should_refuse"] != (i["type"] == "unanswerable"):
            errors.append(f"{i['id']}: should_refuse must be true exactly for unanswerable items")
        if i["type"] == "unanswerable":
            if i["evidence"] or i["gold_chunk_ids"] or not i.get("absent_terms"):
                errors.append(f"{i['id']}: unanswerable needs absent_terms and no evidence/gold ids")
        elif not i["evidence"]:
            errors.append(f"{i['id']}: answerable item has no evidence")
        if i["type"] == "multi_hop" and len(i["evidence"]) < 2:
            errors.append(f"{i['id']}: multi_hop needs >= 2 evidence entries")
    pairs = Counter(i["pair"] for i in items if i["type"] == "near_miss")
    if len(pairs) != 5 or set(pairs.values()) != {2}:
        errors.append(f"near_miss pairs malformed: {dict(pairs)}")
    return errors


async def tenant_chunks(conn: asyncpg.Connection, tenant: str) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = await conn.fetch(
        """
        SELECT d.slug || '#' || c.ordinal AS gid, c.content, c.token_count, c.allowed_roles,
               c.min_clearance, c.embedding
        FROM chunks c
        JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id
        JOIN tenants t ON t.id = c.tenant_id
        WHERE t.slug = $1
        """,
        tenant,
    )
    return rows


def vector_ranks(query: list[float], pool: list[asyncpg.Record]) -> dict[str, int]:
    """1-based rank of every chunk in `pool` by cosine similarity (vectors are unit-norm)."""
    sims = sorted(
        ((sum(a * b for a, b in zip(query, c["embedding"].to_list(), strict=True)), c["gid"]) for c in pool),
        reverse=True,
    )
    return {gid: n for n, (_, gid) in enumerate(sims, 1)}


def permitted(chunk: asyncpg.Record, roles: list[str], clearance: int) -> bool:
    # Mirrors the Phase 3 ACL predicate: empty allowed_roles = all roles in the tenant.
    allowed = chunk["allowed_roles"]
    return (not allowed or bool(set(allowed) & set(roles))) and chunk["min_clearance"] <= clearance


def write_review(items: list[dict[str, Any]]) -> None:
    lines = [
        "# Golden set review listing",
        "",
        "Generated by `uv run python eval/verify_golden.py --write-review` from `eval/golden_set.jsonl`.",
        "Do not edit by hand.",
    ]
    current = None
    for i in items:
        if i["type"] != current:
            current = i["type"]
            lines += [
                "",
                f"## {current}",
                "",
                "| id | tenant | as_user | question | expected answer | gold chunks | tags |",
            ]
            lines.append("|---|---|---|---|---|---|---|")
        gold = "<br>".join(i["gold_chunk_ids"]) or "must be absent: " + "; ".join(i.get("absent_terms", []))
        tags = ", ".join(i["tags"] + [i[k] for k in ("pair", "paraphrase_of") if i.get(k)])
        lines.append(
            f"| {i['id']} | {i['tenant']} | {i['as_user']} | {i['question']} | {i['expected_answer']} "
            f"| {gold} | {tags} |"
        )
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"review listing written to {REVIEW}")


async def main(resolve: bool, review: bool) -> int:
    items = load(GOLDEN)
    errors = check_structure(items)
    settings = get_settings()
    embedder = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    pool = await create_pool(settings.database_dsn)
    buried_report: list[str] = []
    try:
        async with pool.acquire() as conn:
            corpus = {t: await tenant_chunks(conn, t) for t in {i["tenant"] for i in items}}
    finally:
        await pool.close()

    for item in items:
        chunks = corpus[item["tenant"]]
        if not chunks:
            errors.append(f"{item['id']}: tenant {item['tenant']!r} has no chunks; seed the corpus")
            continue
        by_gid = {c["gid"]: c for c in chunks}

        if item["type"] == "unanswerable":
            for term in item["absent_terms"]:
                pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
                hits = [c["gid"] for c in chunks if pattern.search(c["content"])]
                if hits:
                    errors.append(f"{item['id']}: absent term {term!r} found in {hits[:3]}")
            continue

        allowed = [c for c in chunks if permitted(c, item["as_role"], item["as_clearance"])]
        computed: set[str] = set()
        for ev in item["evidence"]:
            found = sorted(c["gid"] for c in allowed if ev["text"] in c["content"])
            if not found:
                anywhere = [c["gid"] for c in chunks if ev["text"] in c["content"]]
                why = f"only in chunks this role cannot read: {anywhere}" if anywhere else "not in corpus"
                errors.append(f"{item['id']}: evidence {ev['text'][:60]!r} {why}")
            if resolve:
                ev["chunk_ids"] = found
            elif ev["chunk_ids"] != found:
                errors.append(f"{item['id']}: stale evidence ids {ev['chunk_ids']} != {found}")
            computed.update(found)

        if resolve:
            item["gold_chunk_ids"] = sorted(computed)
        else:
            missing = [g for g in item["gold_chunk_ids"] if g not in by_gid]
            if missing:
                errors.append(f"{item['id']}: gold ids do not resolve: {missing}")
            if sorted(item["gold_chunk_ids"]) != sorted(computed):
                errors.append(f"{item['id']}: stale gold ids {item['gold_chunk_ids']} != {sorted(computed)}")

        if item["type"] == "multi_hop" and len(computed) < 2:
            errors.append(
                f"{item['id']}: multi_hop evidence lands in fewer than 2 distinct chunks {sorted(computed)}"
            )

        if any(tag in item["tags"] for tag in BURIED_TAGS):
            text = item["evidence"][0]["text"]
            ev_tokens = embedder.count_tokens(text, special_tokens=False)
            q = await embedder.embed_query(item["question"])
            tenant_rank, role_rank = vector_ranks(q, list(chunks)), vector_ranks(q, allowed)
            for gid in sorted(computed):
                chunk = by_gid[gid]
                share = ev_tokens / chunk["token_count"]
                buried_report.append(
                    f"  {item['id']} {gid:40s} {chunk['token_count']:3d} tok, evidence {share:4.1%} "
                    f"| vector rank {tenant_rank[gid]:3d}/{len(chunks)} tenant-wide (Phase 2, no ACL), "
                    f"{role_rank[gid]:2d}/{len(allowed)} role-visible (Phase 3+)"
                )
                if chunk["token_count"] < BURIED_MIN_CHUNK_TOKENS or share > BURIED_MAX_EVIDENCE_SHARE:
                    errors.append(
                        f"{item['id']}: not buried: {gid} has {chunk['token_count']} tokens, "
                        f"evidence share {share:.1%}"
                    )

    if review:
        write_review(items)
    if resolve:
        GOLDEN.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
        print(f"resolved gold ids written to {GOLDEN}")

    counts = Counter(i["type"] for i in items)
    print(
        f"{len(items)} items: {dict(counts)}; buried_fact: {sum('buried_fact' in i['tags'] for i in items)}"
    )
    print("buried_fact gold chunks:")
    print("\n".join(buried_report))
    if errors:
        print(f"\n{len(errors)} problem(s):")
        print("\n".join(f"  - {e}" for e in errors))
        return 1
    print("\nOK: every gold id resolves and every check passes.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--resolve", action="store_true", help="recompute gold ids from evidence and write them"
    )
    parser.add_argument("--write-review", action="store_true", help="regenerate eval/golden_set_review.md")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.resolve, args.write_review)))

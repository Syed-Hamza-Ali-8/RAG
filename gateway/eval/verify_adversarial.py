"""Verify the adversarial (ACL-leakage) set against the current corpus. No LLM calls.

    uv run python eval/verify_adversarial.py                 # verify; exit 1 on any problem
    uv run python eval/verify_adversarial.py --write-review  # also write eval/adversarial_review.md

Each probe is asked by a real seeded user (as_user) and targets a fact that user must never see.

PASS CRITERIA (fixed before any ACL code; applied by tests/test_acl_isolation.py and the eval run):
- P1 retrieval (deterministic, no LLM, CI): every chunk returned by every retrieval path for the probe's
  user is permitted: same tenant AND (allowed_roles empty OR shares a role with the user) AND
  min_clearance <= the user's clearance, using roles, clearance and chunk ACLs as they are in the
  database AT QUERY TIME (never claims baked into a token). Zero tolerance.
  P1 covers every retrieval path that exists when the suite runs: vector now, keyword and graph from
  Phase 5. The entity_leak probes therefore become graph-path tests automatically once the graph path
  exists; no separate graph probes are needed.
- P2 answer: the answer contains none of forbidden_strings (case-insensitive), and every citation
  points to a chunk the user may read. Checkable without an LLM: the runtime citation check already
  refuses answers with no valid citation, so "if no permitted chunk supports an answer, refuse" is
  enforced by the stack and asserted here through the citations.
- P3 audit: each probe query writes one audit_log row whose retrieved_ids are all permitted.
- P4 indistinguishable refusal: a refusal for a probe is identical to the refusal for a genuinely
  unanswerable golden-set question: the same answer text (REFUSAL_MESSAGE, byte for byte), the same
  response shape and status, no wording about access, permissions or restricted documents, and the
  same code path (the LLM is called in both cases; an ACL denial never short-circuits). Latency of the
  two groups is measured and reported; on this machine it is too noisy to be a pass/fail signal, so the
  code-path check is the enforced form of "no different latency signature".
- expected = reject_422 / reject_401: the request is rejected with that status and no answer.
Invariant 11: a failing probe means the code is wrong, never the probe. Probes are never weakened,
skipped, deleted or marked xfail to make a suite pass.

CONSTRUCTION RULES (checked here):
- the user exists in corpus/tenants.json with exactly the probe's roles and clearance (except the
  synthetic deleted-tenant probe, whose tenant and user the test creates and then deletes);
- target_evidence occurs in the corpus of target_tenant, and only in chunks the user may NOT read
  (after the probe's setup, for stale_authorization probes);
- stale_authorization: BEFORE the setup the user could read the target; AFTER it, it cannot;
- each forbidden string occurs in some chunk the user may not read, in no chunk the user may read,
  and not in the question (so echoing the question can never count as a leak);
- the category is accurate: cross_tenant targets another tenant; cross_role targets chunks whose roles
  the user lacks; cross_clearance targets chunks whose role the user HAS but whose clearance it lacks;
  request_tampering and reject_422 probes carry a body tenant (request_overrides);
- liveness: with the ACL predicate removed (and the tenant predicate too, for cross-tenant targets),
  a chunk holding the target evidence ranks in the top LIVE_K by vector similarity. A live probe is
  one that WOULD leak without the filter; this is what "removing the ACL predicate makes the suite
  fail" means, probe by probe.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg

from gateway.config import get_settings
from gateway.db import create_pool
from gateway.ingest.embedder import Embedder

EVAL_DIR = Path(__file__).resolve().parent
ADVERSARIAL = EVAL_DIR / "adversarial_set.jsonl"
REVIEW = EVAL_DIR / "adversarial_review.md"
TENANTS = EVAL_DIR.parent / "corpus" / "tenants.json"
MIN_PROBES = 30
CATEGORIES = (
    "cross_tenant",
    "cross_role",
    "cross_clearance",
    "prompt_injection",
    "entity_leak",
    "request_tampering",
    "stale_authorization",
)
EXPECTED = {"refuse", "no_leak_permitted_citations", "reject_422", "reject_401"}
LIVE_K = 10


def load(path: Path = ADVERSARIAL) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def permitted(chunk: dict[str, Any], tenant: str, roles: list[str], clearance: int) -> bool:
    """The ACL predicate the SQL must implement, stated once for the checker."""
    allowed = chunk["allowed_roles"]
    return (
        chunk["tenant"] == tenant
        and (not allowed or bool(set(allowed) & set(roles)))
        and chunk["min_clearance"] <= clearance
    )


async def all_chunks(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT t.slug AS tenant, d.slug || '#' || c.ordinal AS gid, c.content, c.allowed_roles,
               c.min_clearance, c.embedding
        FROM chunks c JOIN documents d ON d.id = c.document_id JOIN tenants t ON t.id = c.tenant_id
        """
    )
    return [{**dict(r), "embedding": r["embedding"].to_list()} for r in rows]


def after_setup(p: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """The user's roles and the chunk ACLs as they are once the probe's setup has run."""
    setup = p.get("setup", {})
    roles = [r for r in p["as_role"] if r not in setup.get("revoke_roles", [])]
    tighten = setup.get("tighten_document")
    if tighten:
        chunks = [
            {**c, "allowed_roles": tighten["allowed_roles"], "min_clearance": tighten["min_clearance"]}
            if c["tenant"] == p["tenant"] and c["gid"].split("#")[0] == tighten["slug"]
            else c
            for c in chunks
        ]
    return roles, chunks


def check_probe(
    p: dict[str, Any],
    all_chunks_: list[dict[str, Any]],
    query_vec: list[float],
    users: dict[tuple[str, str], Any],
) -> tuple[list[str], int | None]:
    errors: list[str] = []
    pid, tenant, clearance = p["id"], p["tenant"], p["as_clearance"]
    cat, expected, setup = p["category"], p["expected"], p.get("setup", {})
    if cat not in CATEGORIES:
        errors.append(f"{pid}: unknown category {cat}")
    if expected not in EXPECTED:
        errors.append(f"{pid}: unknown expected behaviour {expected}")
    if expected == "reject_422" and "tenant" not in p.get("request_overrides", {}):
        errors.append(f"{pid}: reject_422 probes must send a body tenant")
    if setup.get("synthetic_tenant"):
        if not (expected == "reject_401" and setup.get("delete_tenant") and cat == "stale_authorization"):
            errors.append(f"{pid}: a synthetic-tenant probe must delete its tenant and expect reject_401")
        return errors, None

    user = users.get((tenant, p["as_user"]))
    if user is None or sorted(user["roles"]) != sorted(p["as_role"]) or user["clearance"] != clearance:
        errors.append(f"{pid}: as_user/as_role/as_clearance do not match seeded user {p['as_user']}")
    if not p["target_evidence"]:
        if cat != "request_tampering":
            errors.append(f"{pid}: only request_tampering probes may omit target evidence")
        return errors, None

    def targets_in(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            c
            for c in chunks
            if c["tenant"] == p["target_tenant"] and any(e in c["content"] for e in p["target_evidence"])
        ]

    if cat == "stale_authorization":
        before = [c for c in targets_in(all_chunks_) if permitted(c, tenant, p["as_role"], clearance)]
        if not before:
            errors.append(f"{pid}: stale probe, but the user could not read the target even before the setup")
    roles, chunks = after_setup(p, all_chunks_)
    allowed = [c for c in chunks if permitted(c, tenant, roles, clearance)]
    targets = targets_in(chunks)
    if not targets:
        errors.append(f"{pid}: target evidence not found in {p['target_tenant']}")
    leaked = [c["gid"] for c in targets if permitted(c, tenant, roles, clearance)]
    if leaked:
        errors.append(f"{pid}: target evidence is readable by this user in {leaked}: not a leak probe")

    question = p["question"].lower()
    forbidden_chunks = [c for c in chunks if not permitted(c, tenant, roles, clearance)]
    for s in p["forbidden_strings"]:
        low = s.lower()
        if low in question:
            errors.append(f"{pid}: forbidden string {s!r} appears in the question")
        hits = [c["gid"] for c in allowed if low in c["content"].lower()]
        if hits:
            errors.append(f"{pid}: forbidden string {s!r} is readable by this user in {hits[:3]}")
        if not any(low in c["content"].lower() for c in forbidden_chunks):
            errors.append(f"{pid}: forbidden string {s!r} occurs in no restricted chunk")
    if not p["forbidden_strings"] and expected in ("refuse", "no_leak_permitted_citations"):
        errors.append(f"{pid}: a leak probe needs forbidden strings")

    if cat == "cross_tenant" and p["target_tenant"] == tenant:
        errors.append(f"{pid}: cross_tenant probe targets its own tenant")
    if cat in ("cross_role", "cross_clearance", "stale_authorization") and p["target_tenant"] != tenant:
        errors.append(f"{pid}: {cat} probe must target its own tenant")
    for c in targets:
        has_role = not c["allowed_roles"] or bool(set(c["allowed_roles"]) & set(roles))
        if cat == "cross_role" and has_role:
            errors.append(f"{pid}: cross_role target {c['gid']} is not role-restricted for this user")
        if cat == "cross_clearance" and not (has_role and c["min_clearance"] > clearance):
            errors.append(f"{pid}: cross_clearance target {c['gid']} is not blocked by clearance alone")

    # Liveness: rank among the candidates the system would see with the predicate removed.
    pool = chunks if p["target_tenant"] != tenant else [c for c in chunks if c["tenant"] == tenant]
    sims = sorted(
        (
            (sum(a * b for a, b in zip(query_vec, c["embedding"], strict=True)), c["gid"], c["tenant"])
            for c in pool
        ),
        reverse=True,
    )
    target_keys = {(c["gid"], c["tenant"]) for c in targets}
    rank = next((n for n, (_, g, t) in enumerate(sims, 1) if (g, t) in target_keys), None)
    if rank is None or rank > LIVE_K:
        errors.append(
            f"{pid}: not live: best target chunk ranks {rank} without the filter (need <= {LIVE_K})"
        )
    return errors, rank


def write_review(probes: list[dict[str, Any]], ranks: dict[str, int | None]) -> None:
    lines = [
        "# Adversarial set review listing",
        "",
        "Generated by `uv run python eval/verify_adversarial.py --write-review`. Do not edit by hand.",
        "Liveness rank: where the forbidden chunk ranks among candidates with the ACL filter removed "
        f"(live if <= {LIVE_K}).",
    ]
    current = None
    for p in probes:
        if p["category"] != current:
            current = p["category"]
            lines += [
                "",
                f"## {current}",
                "",
                "| id | user | question | target | forbidden in answer | live rank | note |",
                "|---|---|---|---|---|---|---|",
            ]
        override = f" (body: {p['request_overrides']})" if p.get("request_overrides") else ""
        lines.append(
            f"| {p['id']} | {p['tenant']}/{p['as_user'].split('@')[0]}{override} | {p['question']} "
            f"| {p['target_tenant']}: {'; '.join(p['target_evidence'])} "
            f"| {', '.join(p['forbidden_strings'])} "
            f"| {ranks.get(p['id'])} | {p['note']} |"
        )
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"review listing written to {REVIEW}")


async def main(review: bool) -> int:
    probes = load()
    users = {
        (t["slug"], u["email"]): u
        for t in json.loads(TENANTS.read_text(encoding="utf-8"))["tenants"]
        for u in t["users"]
    }
    errors: list[str] = []
    if len(probes) < MIN_PROBES:
        errors.append(f"only {len(probes)} probes (need >= {MIN_PROBES})")
    if len({p["id"] for p in probes}) != len(probes):
        errors.append("duplicate probe ids")
    counts = Counter(p["category"] for p in probes)
    errors += [f"no probes in category {c}" for c in CATEGORIES if not counts[c]]

    settings = get_settings()
    embedder = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            chunks = await all_chunks(conn)
    finally:
        await pool.close()
    ranks: dict[str, int | None] = {}
    for p in probes:
        probe_errors, ranks[p["id"]] = check_probe(
            p, chunks, await embedder.embed_query(p["question"]), users
        )
        errors += probe_errors

    print(f"{len(probes)} probes: {dict(counts)}")
    print(
        "liveness ranks (forbidden chunk, filter removed): " + ", ".join(f"{k}={v}" for k, v in ranks.items())
    )
    if review:
        write_review(probes, ranks)
    if errors:
        print(f"\n{len(errors)} problem(s):\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print("\nOK: every probe is well-formed, targets a fact its user may not read, and is live.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--write-review", action="store_true", help="regenerate eval/adversarial_review.md")
    sys.exit(asyncio.run(main(parser.parse_args().write_review)))

"""Verify the semantic-cache adversarial set against the current corpus and users. No LLM calls.

    uv run python eval/verify_adversarial_cache.py                 # verify; exit 1 on any problem
    uv run python eval/verify_adversarial_cache.py --write-review  # also write the review listing

Each probe makes two requests through POST /v1/query: `populate` (may store a cache entry) then `ask`.

PASS CRITERIA (fixed before any cache code; applied by tests/test_cache_isolation.py):
- C1 scope: `ask` is served from a cache entry only if the entry's tenant_id equals the caller's tenant
  AND its role_signature equals the caller's signature, computed from the caller's roles and clearance
  as the database holds them at query time. role_signature = sha256 of the sorted, de-duplicated roles
  plus the clearance (spec 4.2). Zero tolerance.
- C2 no leak: the answer to `ask` contains none of forbidden_strings (values readable by the populating
  user and by no chunk the asking user may read).
- C3 near-miss: for every near-miss pair, `ask` (question B) is never served the entry stored for
  question A, at the configured threshold and at every threshold of the tuning sweep (0.88-0.99).
  Similarity alone cannot pass this for nm2 (cosine 0.9948): the defence must not depend on the threshold.
- C4 invalidation (correction K): any document ingest, delete or ACL change in a tenant removes ALL of
  that tenant's entries; other tenants' entries are untouched (k20 is the control).
- C5 bypass: a question matching the temporal/entity deny-list is neither served from nor written to the
  cache (no row for it exists after both requests).
- C6 non-vacuity: every `expected: hit` control is served from the cache, so a suite that never hits fails.
- C7 audit on a hit (correction O): served_from_cache = true and retrieved_ids = the cached citations'
  chunk ids, never empty.
- C8 only answered outcomes are stored: after a refused (or truncated) request no cache row exists for it.
expected = miss: `ask` is not served from the populate request's entry; expected = hit: it is.

LIVENESS (checked here, and re-proved by mutation in the test suite):
- cross_role / cross_clearance / cross_tenant / stale probes ask the IDENTICAL question twice (cosine 1.0),
  so any cache keyed without the separating component (role signature, tenant, fresh state) would hit;
- cross_role / cross_clearance pairs differ in signature within one tenant; cross_tenant pairs have the
  SAME signature in different tenants, so only tenant_id separates them;
- near-miss pairs have cosine >= 0.88, so a similarity-only cache at the bottom of the sweep conflates
  every one of them.
Invariant 11: a failing probe means the code is wrong, never the probe.
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
from gateway.ingest.embedder import Embedder
from verify_adversarial import all_chunks, permitted

EVAL_DIR = Path(__file__).resolve().parent
PROBES_FILE = EVAL_DIR / "adversarial_cache.jsonl"
REVIEW = EVAL_DIR / "adversarial_cache_review.md"
GOLDEN = EVAL_DIR / "golden_set.jsonl"
TENANTS = EVAL_DIR.parent / "corpus" / "tenants.json"
CATEGORIES = (
    "cross_role",
    "cross_clearance",
    "cross_tenant",
    "near_miss",
    "stale",
    "bypass",
    "control",
    "non_cacheable",
)
SWEEP_LOW = 0.88


def role_signature(roles: list[str], clearance: int) -> str:
    """Reference definition (spec 4.2); the production function must agree with it."""
    return hashlib.sha256(json.dumps([sorted(set(roles)), clearance]).encode()).hexdigest()


def load(path: Path = PROBES_FILE) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def questions(p: dict[str, Any]) -> tuple[str, str]:
    return p["populate"].get("question", p.get("question", "")), p["ask"].get(
        "question", p.get("question", "")
    )


def check_probe(
    p: dict[str, Any], users: dict[tuple[str, str], dict[str, Any]], chunks: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    pid, cat, setup = p["id"], p["category"], p.get("setup", {})
    if cat not in CATEGORIES:
        errors.append(f"{pid}: unknown category {cat}")
    twin = setup.get("synthetic_same_signature_user")
    sides = {}
    for side in ("populate", "ask"):
        key = (p[side]["tenant"], p[side]["as_user"])
        if twin and side == "ask" and key[1] == twin["email"]:
            sides[side] = {"roles": twin["roles"], "clearance": twin["clearance"]}
        elif key not in users:
            errors.append(f"{pid}: {side} user {key} is not seeded")
            return errors
        else:
            sides[side] = users[key]
    sig = {s: role_signature(sides[s]["roles"], sides[s]["clearance"]) for s in sides}
    same_tenant = p["populate"]["tenant"] == p["ask"]["tenant"]
    q_pop, q_ask = questions(p)

    if cat in ("cross_role", "cross_clearance", "cross_tenant", "stale", "bypass", "non_cacheable") or (
        cat == "control" and twin
    ):
        if q_pop != q_ask:
            errors.append(f"{pid}: {cat} probes must ask the identical question twice")
    if cat in ("cross_role", "cross_clearance"):
        if not same_tenant or sig["populate"] == sig["ask"]:
            errors.append(f"{pid}: {cat} needs one tenant and two different role signatures")
        roles_equal = sorted(sides["populate"]["roles"]) == sorted(sides["ask"]["roles"])
        if cat == "cross_clearance" and not (
            roles_equal and sides["populate"]["clearance"] != sides["ask"]["clearance"]
        ):
            errors.append(f"{pid}: cross_clearance needs equal roles and different clearance")
        if cat == "cross_role" and roles_equal:
            errors.append(f"{pid}: cross_role needs different roles")
    if cat == "cross_tenant" and (same_tenant or sig["populate"] != sig["ask"]):
        errors.append(f"{pid}: cross_tenant needs two tenants and the SAME role signature")
    if cat in ("stale", "bypass", "non_cacheable") or (cat == "control" and not twin):
        if p["populate"] != p["ask"] and not (cat == "control" and q_pop.lower().strip("?") == q_ask.lower()):
            errors.append(f"{pid}: {cat} probes are asked twice by the same user")
    if twin and sig["populate"] != sig["ask"]:
        errors.append(f"{pid}: the synthetic twin must have the populating user's signature")
    if cat in ("near_miss",) and (p["populate"]["as_user"] != p["ask"]["as_user"] or q_pop == q_ask):
        errors.append(f"{pid}: near-miss probes ask two different questions as one user")
    expected = {"stale": {"miss", "hit"}, "bypass": {"bypass"}, "control": {"hit"}}.get(cat, {"miss"})
    if p["expected"] not in expected:
        errors.append(f"{pid}: {cat} probes expect {sorted(expected)}, not {p['expected']}")

    # Forbidden strings: readable by the populating user, readable by no chunk the asker may read (after
    # setup), absent from the question.
    ask_roles = [r for r in sides["ask"]["roles"] if r not in setup.get("revoke_roles", [])]
    tighten = setup.get("tighten_document")
    changed = setup.get("reingest_changed_text")
    for s in p["forbidden_strings"]:
        low = s.lower()
        if low in q_ask.lower():
            errors.append(f"{pid}: forbidden string {s!r} appears in the question")
        if not any(
            low in c["content"].lower()
            and permitted(
                c, p["populate"]["tenant"], sides["populate"]["roles"], sides["populate"]["clearance"]
            )
            for c in chunks
        ):
            errors.append(f"{pid}: forbidden string {s!r} is not readable by the populating user")
        for c in chunks:
            if tighten and c["tenant"] == p["ask"]["tenant"] and c["gid"].split("#")[0] == tighten["slug"]:
                c = {
                    **c,
                    "allowed_roles": tighten["allowed_roles"],
                    "min_clearance": tighten["min_clearance"],
                }
            if changed and c["tenant"] == p["ask"]["tenant"] and c["gid"].split("#")[0] == changed["slug"]:
                c = {**c, "content": c["content"].replace(*changed["replace"])}
            if low in c["content"].lower() and permitted(
                c, p["ask"]["tenant"], ask_roles, sides["ask"]["clearance"]
            ):
                errors.append(f"{pid}: forbidden string {s!r} is readable by the asking user in {c['gid']}")
                break
    if (
        cat in ("cross_role", "cross_clearance", "cross_tenant")
        and not p["forbidden_strings"]
        and pid != "k09"
    ):
        errors.append(f"{pid}: a leak probe needs forbidden strings")
    return errors


async def main(review: bool) -> int:
    probes = load()
    users = {
        (t["slug"], u["email"]): u
        for t in json.loads(TENANTS.read_text(encoding="utf-8"))["tenants"]
        for u in t["users"]
    }
    golden = {
        g["id"]: g
        for g in (json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip())
    }
    errors: list[str] = []
    if len({p["id"] for p in probes}) != len(probes):
        errors.append("duplicate probe ids")
    settings = get_settings()
    pool = await create_pool(settings.database_dsn)
    try:
        async with pool.acquire() as conn:
            chunks = await all_chunks(conn)
    finally:
        await pool.close()
    embedder = Embedder(settings.embedding_model_id, settings.embedding_dim, settings.embedding_cache_dir)
    cosines: dict[str, float] = {}
    for p in probes:
        errors += check_probe(p, users, chunks)
        if p["category"] == "near_miss":
            pair = [g for g in golden.values() if g.get("pair") == p["pair"]]
            q_pop, q_ask = questions(p)
            if sorted(g["question"] for g in pair) != sorted([q_pop, q_ask]):
                errors.append(f"{p['id']}: questions are not golden pair {p['pair']}")
            if any(g["as_user"] != p["ask"]["as_user"] for g in pair):
                errors.append(f"{p['id']}: user differs from the golden pair's as_user")
            a, b = await embedder.embed_query(q_pop), await embedder.embed_query(q_ask)
            cosines[p["id"]] = sum(x * y for x, y in zip(a, b, strict=True))
            if cosines[p["id"]] < SWEEP_LOW:
                errors.append(f"{p['id']}: not live: cosine {cosines[p['id']]:.4f} < {SWEEP_LOW}")
    pairs_in_set = {p["pair"] for p in probes if p["category"] == "near_miss"}
    pairs_golden = {g["pair"] for g in golden.values() if g["type"] == "near_miss"}
    if pairs_in_set != pairs_golden:
        errors.append(f"near-miss pairs {sorted(pairs_golden - pairs_in_set)} missing")

    counts: dict[str, int] = {}
    for p in probes:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print(f"{len(probes)} cache probes: {counts}")
    print("near-miss cosines: " + ", ".join(f"{k}={v:.4f}" for k, v in cosines.items()))
    if review:
        write_review(probes, cosines)
    if errors:
        print(f"\n{len(errors)} problem(s):\n" + "\n".join(f"  - {e}" for e in errors))
        return 1
    print("\nOK: every probe is well-formed and live.")
    return 0


def who(side: dict[str, Any]) -> str:
    return f"{side['tenant']}/{side['as_user'].split('@')[0]}"


def write_review(probes: list[dict[str, Any]], cosines: dict[str, float]) -> None:
    lines = [
        "# Cache adversarial set review listing",
        "",
        "Generated by `uv run python eval/verify_adversarial_cache.py --write-review`. Do not edit by hand.",
        "Pass criteria C1-C7 are in the verifier's docstring.",
        "",
        "| id | category | populate | ask | question(s) | expected | forbidden in answer | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in probes:
        q_pop, q_ask = questions(p)
        qs = q_pop if q_pop == q_ask else f"A: {q_pop}<br>B: {q_ask} (cos {cosines.get(p['id'], 0):.4f})"
        setup = f" setup: {json.dumps(p['setup'])}" if p.get("setup") else ""
        lines.append(
            f"| {p['id']} | {p['category']} | {who(p['populate'])} | {who(p['ask'])} | {qs} "
            f"| {p['expected']} | {', '.join(p['forbidden_strings'])} | {p['note']}{setup} |"
        )
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"review listing written to {REVIEW}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--write-review", action="store_true", help="regenerate eval/adversarial_cache_review.md"
    )
    sys.exit(asyncio.run(main(parser.parse_args().write_review)))

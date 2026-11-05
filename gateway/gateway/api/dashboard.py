"""Phase 6 dashboard: a static shell plus admin-only data endpoints (EVAL_RESULTS.md, Phase 6 dashboard
design).

- `GET /dashboard` is the shell (HTMX + Chart.js from CDN). It holds no data and needs no token.
- `GET /v1/dashboard/{summary,feed,audit,eval}` require the admin role, read from the database per request.
  The tenant comes only from the token; no endpoint accepts a tenant, and every log query is scoped by
  `acl.tenant_predicate`. Eval judge calls are excluded from every metric.
- Question text is never shown (option C): every row keeps its time, user, roles, outcome, counts and latency,
  with the question replaced by a marker.
- Never shown: answer text (`query_log.answer_raw` may quote content the admin may not read) and chunk
  content. Retrieved chunks appear as counts, plus the titles of those the admin may read
  (gateway.retrieval.titles).
- Jinja2 autoescaping is on for every template: question text is user-typed and is rendered as text, never
  markup.
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from gateway.deps import AuthContext, require_admin
from gateway.retrieval.titles import readable_titles
from gateway.security import acl

TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

shell = APIRouter()
router = APIRouter(prefix="/v1/dashboard")
Admin = Annotated[AuthContext, Depends(require_admin)]

# Aggregates served from each committed baseline: an allowlist, so no per-item field can ever leave.
_EVAL_RETRIEVAL = ("recall@6", "all_hops@10", "mrr")
_EVAL_GENERATION = (
    "correct_answerable",
    "faithful",
    "citations_supported",
    "correct_refusal_unanswerable",
    "false_refusal_answerable",
)


@shell.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_shell(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {})


def _summary_sql() -> str:
    # $1 tenant, $2 window in hours. Queries only (purpose = 'query'); judge calls excluded.
    return (
        "SELECT count(*) AS queries,"  # noqa: S608
        " count(*) FILTER (WHERE q.outcome = 'answered') AS answered,"
        " count(*) FILTER (WHERE q.outcome = 'refused') AS refused,"
        " count(*) FILTER (WHERE q.outcome = 'truncated') AS truncated,"
        " count(*) FILTER (WHERE q.cache_hit) AS cache_hits,"
        " count(*) FILTER (WHERE q.cache_hit IS NOT NULL) AS cache_consulted,"
        " avg(q.est_cost_usd) FILTER (WHERE q.cache_hit IS NOT TRUE AND q.outcome = 'answered') AS miss_cost,"
        " sum(q.est_cost_usd) AS shadow_cost, count(q.est_cost_usd) AS costed,"
        " percentile_cont(0.5) WITHIN GROUP (ORDER BY q.total_ms) AS p50_ms,"
        " percentile_cont(0.95) WITHIN GROUP (ORDER BY q.total_ms) AS p95_ms"
        " FROM query_log q WHERE " + acl.tenant_predicate("q", 1) + " AND q.purpose = 'query'"
        " AND q.ts > now() - make_interval(hours => $2)"
    )


def _routing_sql() -> str:
    return (
        "SELECT coalesce(q.route_tier, 'none') AS tier, count(*) AS n FROM query_log q"  # noqa: S608
        " WHERE " + acl.tenant_predicate("q", 1) + " AND q.purpose = 'query'"
        " AND q.ts > now() - make_interval(hours => $2) GROUP BY 1 ORDER BY 2 DESC"
    )


def _hourly_sql() -> str:
    return (
        "SELECT date_trunc('hour', q.ts) AS hour, count(*) AS n,"  # noqa: S608
        " percentile_cont(0.95) WITHIN GROUP (ORDER BY q.total_ms) AS p95_ms FROM query_log q"
        " WHERE " + acl.tenant_predicate("q", 1) + " AND q.purpose = 'query'"
        " AND q.ts > now() - make_interval(hours => $2) GROUP BY 1 ORDER BY 1"
    )


def _feed_sql(role_filter: bool) -> str:
    # $1 tenant, $2 limit[, $3 role]. One row per audited query, joined to its query_log row and its user.
    # No answer column is selected.
    return (
        "SELECT a.ts, u.email, a.user_roles, a.query_text, a.refused, a.served_from_cache, a.denied_count,"  # noqa: S608
        " a.retrieved_ids, q.outcome, q.route_tier, q.total_ms, q.citations_valid"
        " FROM audit_log a"
        " LEFT JOIN query_log q ON q.id = a.query_log_id AND q.tenant_id = a.tenant_id"
        " LEFT JOIN users u ON u.id = a.user_id AND u.tenant_id = a.tenant_id"
        " WHERE "
        + acl.tenant_predicate("a", 1)
        + (" AND $3 = ANY(a.user_roles)" if role_filter else "")
        + " ORDER BY a.ts DESC, a.id DESC LIMIT $2"
    )


@router.get("/summary")
async def summary(
    request: Request, admin: Admin, hours: Annotated[int, Query(ge=1, le=720)] = 168
) -> dict[str, Any]:
    async with request.app.state.pool.acquire() as conn:
        s = await conn.fetchrow(_summary_sql(), admin.tenant_id, hours)
        routing = await conn.fetch(_routing_sql(), admin.tenant_id, hours)
        hourly = await conn.fetch(_hourly_sql(), admin.tenant_id, hours)
    consulted = s["cache_consulted"]
    miss_cost = float(s["miss_cost"]) if s["miss_cost"] is not None else None
    return {
        "window_hours": hours,
        "queries": s["queries"],
        "outcomes": {"answered": s["answered"], "refused": s["refused"], "truncated": s["truncated"]},
        "cache": {
            "hits": s["cache_hits"],
            "consulted": consulted,
            "hit_rate": round(s["cache_hits"] / consulted, 4) if consulted else None,
        },
        "cost_usd": {
            "shadow_total": float(s["shadow_cost"]) if s["shadow_cost"] is not None else None,
            "costed_queries": s["costed"],  # rows with a recorded shadow cost (none before Phase 4)
            "modelled_saved": round(s["cache_hits"] * miss_cost, 6) if miss_cost is not None else None,
            "model": "cache hits x mean shadow cost of answered misses in the window",
        },
        "latency_ms": {
            "p50": round(s["p50_ms"]) if s["p50_ms"] is not None else None,
            "p95": round(s["p95_ms"]) if s["p95_ms"] is not None else None,
        },
        "routing": {r["tier"]: r["n"] for r in routing},
        "hourly": [
            {"hour": r["hour"].isoformat(), "queries": r["n"], "p95_ms": round(r["p95_ms"] or 0)}
            for r in hourly
        ],
    }


def question_visible(retrieved: int, readable: int, denied: int) -> bool:
    """Option C: question text is never shown on this dashboard. Redacting by retrieved-chunk readability,
    then by any ACL denial, hid 97% of rows on this corpus (everyday questions sit next to role-restricted
    chunks), so the column was withheld or arbitrary. Question text needs a dedicated audit-reviewer role,
    which is not built (EVAL_RESULTS.md, Phase 6 dashboard, option C). This is the one switch; the isolation
    suite's live control flips it to prove nothing else hides the text."""
    return False


async def _with_access(
    conn: asyncpg.Connection, admin: AuthContext, rows: list[asyncpg.Record]
) -> list[dict[str, Any]]:
    """Each row with the titles the admin may read, the withheld count, and the question only when visible.
    A redacted question is dropped here, so it never reaches a template."""
    out = []
    for r in rows:
        ids = list(r["retrieved_ids"])
        titles, readable = await readable_titles(conn, admin.acl(), ids)
        visible = question_visible(len(ids), readable, r["denied_count"])
        out.append(
            {
                **dict(r),
                "query_text": r["query_text"] if visible else None,
                "question_visible": visible,
                "titles": titles,
                "withheld": len(ids) - readable,
            }
        )
    return out


@router.get("/feed", response_class=HTMLResponse)
async def feed(
    request: Request, admin: Admin, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> HTMLResponse:
    async with request.app.state.pool.acquire() as conn:
        rows = await _with_access(conn, admin, await conn.fetch(_feed_sql(False), admin.tenant_id, limit))
    return TEMPLATES.TemplateResponse(request, "_feed.html", {"rows": rows})


@router.get("/audit", response_class=HTMLResponse)
async def audit(
    request: Request,
    admin: Admin,
    role: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HTMLResponse:
    async with request.app.state.pool.acquire() as conn:
        rows = (
            await conn.fetch(_feed_sql(True), admin.tenant_id, limit, role)
            if role
            else await conn.fetch(_feed_sql(False), admin.tenant_id, limit)
        )
        items = await _with_access(conn, admin, rows)
    return TEMPLATES.TemplateResponse(request, "_audit.html", {"rows": items, "role": role})


@router.get("/eval")
async def eval_history(request: Request, admin: Admin) -> list[dict[str, Any]]:
    """Score history from the committed baselines: allowlisted aggregates only, never per-item records."""
    return await asyncio.to_thread(_eval_history, request.app.state.settings.eval_baselines_dir)


def _eval_history(directory: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(directory.glob("phase-*.json"), key=lambda p: int(p.stem.split("-")[1])):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta, agg = data["meta"], data["aggregate"]
        r, g = agg["retrieval"], agg["generation"]
        out.append(
            {
                "baseline": meta.get("baseline") or path.stem,
                "finished_utc": meta.get("finished_utc"),
                "retrieval_mode": meta.get("retrieval_mode", "vector"),
                "retrieval": {
                    cls: {k: r[cls].get(k) for k in _EVAL_RETRIEVAL}
                    for cls in ("single_hop", "multi_hop", "buried_fact")
                    if cls in r
                },
                "generation": {
                    k: (g[k]["rate"] if isinstance(g.get(k), dict) else None) for k in _EVAL_GENERATION
                },
            }
        )
    return out

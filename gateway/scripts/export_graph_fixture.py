"""Export the extracted graph (entities + relations, prompt extract-v1-low) as a test fixture keyed by
tenant slug, document slug and chunk ordinal, so the isolation suites run against the real graph
(EVAL_RESULTS.md, Phase 5 gate).

    uv run python scripts/export_graph_fixture.py   # writes tests/fixtures/graph_extract_v1_low.json

Synthetic corpus only (invariant 14); the fixture holds entity names and relation labels, no chunk content.
"""

import asyncio
import json
from pathlib import Path

from gateway.config import get_settings
from gateway.db import create_pool

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "graph_extract_v1_low.json"


async def main() -> None:
    pool = await create_pool(get_settings().database_dsn)
    try:
        entities = await pool.fetch(
            "SELECT t.slug AS tenant, e.name, e.norm, e.entity_type, e.aliases FROM entities e "
            "JOIN tenants t ON t.id = e.tenant_id ORDER BY 1, 3"
        )
        relations = await pool.fetch(
            "SELECT t.slug AS tenant, s.norm AS source, o.norm AS target, r.relation, d.slug AS document, "
            "c.ordinal FROM relations r JOIN tenants t ON t.id = r.tenant_id "
            "JOIN entities s ON s.id = r.source_id JOIN entities o ON o.id = r.target_id "
            "JOIN chunks c ON c.id = r.chunk_id JOIN documents d ON d.id = c.document_id "
            "ORDER BY 1, 5, 6, 2, 3, 4"
        )
    finally:
        await pool.close()
    OUT.write_text(
        json.dumps(
            {
                "prompt_version": "extract-v1-low",
                "entities": [dict(r) for r in entities],
                "relations": [dict(r) for r in relations],
            },
            indent=0,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT}: {len(entities)} entities, {len(relations)} relations")


if __name__ == "__main__":
    asyncio.run(main())

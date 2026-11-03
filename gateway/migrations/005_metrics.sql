-- 005_metrics: query_log. Built in Phase 1 (CLAUDE.md correction C).
-- Cache, routing and cost columns stay NULL until Phase 4 populates them.
CREATE TABLE query_log (
    id                BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cache_hit         BOOLEAN,                 -- NULL until Phase 4
    route_tier        TEXT,                    -- 'small' | 'large' | 'local' | 'cached'
    complexity_score  REAL,                    -- NULL until Phase 4
    model_used        TEXT,
    prompt_tokens     INT,
    completion_tokens INT,
    est_cost_usd      NUMERIC(10,6),           -- NULL until Phase 4 (shadow cost)
    retrieval_ms      INT,
    llm_ms            INT,
    total_ms          INT,
    refused           BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_query_log_tenant_ts ON query_log (tenant_id, ts);

-- 002_audit_log: one row per query: who asked, what they asked, exactly which chunks reached the
-- LLM, and how many candidates the ACL filtered out. CLAUDE.md correction A (002 holds audit_log
-- only) and correction O (served_from_cache; never an empty retrieved_ids on a cache hit).
CREATE TABLE audit_log (
    id                BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id           UUID NOT NULL,              -- no FK: the trail outlives a deleted user
    user_roles        TEXT[] NOT NULL,            -- as read from the database at query time
    user_clearance    INT NOT NULL,
    query_text        TEXT NOT NULL,
    retrieved_ids     UUID[] NOT NULL,            -- exactly which chunks reached the LLM
    denied_count      INT NOT NULL DEFAULT 0,     -- top-k tenant candidates removed by the ACL predicate
    refused           BOOLEAN NOT NULL,
    answer_hash       TEXT NOT NULL,              -- sha256 of the answer returned to the user
    served_from_cache BOOLEAN NOT NULL DEFAULT false,
    query_log_id      BIGINT,
    CHECK (NOT served_from_cache OR cardinality(retrieved_ids) > 0)
);

CREATE INDEX idx_audit_log_tenant_ts ON audit_log (tenant_id, ts);
CREATE INDEX idx_audit_log_tenant_user_ts ON audit_log (tenant_id, user_id, ts);

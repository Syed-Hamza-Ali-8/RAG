-- 004_graph: entities, relations and the extraction log (spec 4.3, Phase 5; corrections L, M, T).
-- Entities are never exposed directly (correction L): a caller reaches an entity only through a relation whose
-- provenance chunk passes the ACL predicate, and every traversed relation is filtered, not just the last
-- (correction T). Entities are resolved by normalised name within a tenant, whatever type each mention got.
CREATE TABLE entities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,                 -- first surface form seen
    norm        TEXT NOT NULL,                 -- normalised name: the resolution key
    entity_type TEXT NOT NULL CHECK (entity_type IN ('PERSON', 'ORG', 'CONTRACT', 'POLICY', 'DATE', 'PRODUCT')),
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    embedding   vector(384),
    UNIQUE (tenant_id, norm)
);

CREATE TABLE relations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,                 -- short verb phrase from the extractor
    chunk_id    UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,   -- provenance
    confidence  REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX idx_rel_src   ON relations (tenant_id, source_id);
CREATE INDEX idx_rel_tgt   ON relations (tenant_id, target_id);
CREATE INDEX idx_rel_chunk ON relations (tenant_id, chunk_id);

-- One row per extraction attempt: provenance for re-extraction comparability, cost and time per document
-- (a Phase 5 gate item), and resumability (a chunk with an 'ok' row for the same prompt version is done).
CREATE TABLE graph_extraction (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    chunk_id          UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model_used        TEXT NOT NULL,
    prompt_version    TEXT NOT NULL,
    prompt_tokens     INT,
    completion_tokens INT,
    llm_ms            INT,
    outcome           TEXT NOT NULL CHECK (outcome IN ('ok', 'invalid_json', 'truncated', 'error')),
    entities          INT NOT NULL DEFAULT 0,
    relations         INT NOT NULL DEFAULT 0,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_graph_extraction_chunk ON graph_extraction (tenant_id, chunk_id, prompt_version);

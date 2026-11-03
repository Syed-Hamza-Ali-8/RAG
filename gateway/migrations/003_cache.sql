-- 003_cache: tenant- and permission-scoped semantic cache (spec 4.2, CLAUDE.md invariant 4, correction K).
-- A lookup matches only within (tenant_id, role_signature) and only an entry with the same content words
-- (content_key); cosine similarity is a second filter below that (EVAL_RESULTS.md, Phase 4 finding).
CREATE TABLE semantic_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Cache key includes the permission scope. Two users with different roles
    -- MUST NOT share a cache entry, or the cache becomes a leakage channel.
    role_signature  TEXT NOT NULL,            -- sha256 of sorted(roles) + clearance
    content_key     TEXT NOT NULL,            -- sorted content words of the question
    query_text      TEXT NOT NULL,
    query_embedding vector(384) NOT NULL,
    answer          TEXT NOT NULL,
    citations       JSONB NOT NULL,           -- the Citation objects returned with the answer
    model_used      TEXT NOT NULL,
    hit_count       INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    CHECK (jsonb_typeof(citations) = 'array' AND jsonb_array_length(citations) > 0)
);
CREATE INDEX idx_cache_scope ON semantic_cache (tenant_id, role_signature, content_key);
CREATE INDEX idx_cache_vec   ON semantic_cache USING hnsw (query_embedding vector_cosine_ops);

-- Correction K: any document ingest, delete or ACL change wipes ALL of that tenant's entries. Done by
-- triggers so that no write path (ingest, seed, scripts, a direct ACL UPDATE) can forget it.
CREATE FUNCTION semantic_cache_wipe_tenants() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM semantic_cache WHERE tenant_id IN (SELECT DISTINCT tenant_id FROM changed);
    RETURN NULL;
END;
$$;

CREATE TRIGGER documents_insert_wipes_cache AFTER INSERT ON documents
    REFERENCING NEW TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();
CREATE TRIGGER documents_update_wipes_cache AFTER UPDATE ON documents
    REFERENCING NEW TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();
CREATE TRIGGER documents_delete_wipes_cache AFTER DELETE ON documents
    REFERENCING OLD TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();
CREATE TRIGGER chunks_insert_wipes_cache AFTER INSERT ON chunks
    REFERENCING NEW TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();
CREATE TRIGGER chunks_update_wipes_cache AFTER UPDATE ON chunks
    REFERENCING NEW TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();
CREATE TRIGGER chunks_delete_wipes_cache AFTER DELETE ON chunks
    REFERENCING OLD TABLE AS changed FOR EACH STATEMENT EXECUTE FUNCTION semantic_cache_wipe_tenants();

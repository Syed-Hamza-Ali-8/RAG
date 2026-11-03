-- 001_init: tenants, users, documents, chunks.
-- ACL lives as columns on chunks (CLAUDE.md correction A); there is no chunk_acl table.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email        TEXT NOT NULL,
    roles        TEXT[] NOT NULL DEFAULT '{}',
    clearance    INT  NOT NULL DEFAULT 0,        -- 0=public .. 3=restricted
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);

CREATE TABLE documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug         TEXT NOT NULL,                  -- deterministic, e.g. "hr-leave-policy" (correction F)
    title        TEXT NOT NULL,
    source_uri   TEXT,
    mime_type    TEXT,
    doc_metadata JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE chunks (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id    UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal        INT NOT NULL,
    content        TEXT NOT NULL,
    heading_path   TEXT,
    token_count    INT NOT NULL,
    embedding      vector(384) NOT NULL,
    fts            tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    allowed_roles  TEXT[] NOT NULL DEFAULT '{}',   -- empty = all roles in tenant
    min_clearance  INT    NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);

-- tenant_id FIRST in every composite index
CREATE INDEX idx_documents_tenant    ON documents (tenant_id);
CREATE INDEX idx_chunks_tenant_doc   ON chunks (tenant_id, document_id);
CREATE INDEX idx_chunks_fts          ON chunks USING GIN (fts);
CREATE INDEX idx_chunks_roles        ON chunks USING GIN (allowed_roles);
CREATE INDEX idx_chunks_embedding    ON chunks USING hnsw (embedding vector_cosine_ops);

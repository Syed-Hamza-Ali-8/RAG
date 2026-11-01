-- 011_chunks_fts: Postgres full-text search over chunks for hybrid retrieval (Phase 5, M1).
-- The vector is derived from the same text the embedder sees (heading path + content), english config.
-- Generated, so ingest never has to remember it; GIN-indexed. The keyword query always carries the ACL
-- predicate and the tenant scope in its WHERE clause (invariants 1-2), like every other retrieval path.
ALTER TABLE chunks
    ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(heading_path, '') || ' ' || content)) STORED;
CREATE INDEX idx_chunks_tsv ON chunks USING GIN (content_tsv);

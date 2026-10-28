-- 010_query_log_cache_lookup: time spent in the semantic-cache lookup (and its ACL re-check), per query.
-- NULL when the cache was not consulted (disabled or bypassed). On a miss it is pure overhead, which the
-- Phase 4 sweep's cold phase measures (EVAL_RESULTS.md).
ALTER TABLE query_log ADD COLUMN cache_lookup_ms INT;

-- 008_query_log_purpose: separate eval judge calls from real queries in query_log.
-- Judge calls are logged so every model's daily token use is visible to the eval pre-flight
-- check; metrics and dashboards over real traffic must filter purpose = 'query'.
ALTER TABLE query_log
    ADD COLUMN purpose TEXT NOT NULL DEFAULT 'query'
        CHECK (purpose IN ('query', 'eval_judge'));

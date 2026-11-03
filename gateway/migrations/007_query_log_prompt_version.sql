-- 007_query_log_prompt_version: the prompt template version used for each query.
-- Runs under different prompt versions are not comparable; this makes them separable.
-- NULL for rows written before this migration and for queries that made no LLM call.
ALTER TABLE query_log ADD COLUMN prompt_version TEXT;

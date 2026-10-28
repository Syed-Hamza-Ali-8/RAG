-- 009_query_log_outcome: what happened to a generation, as its own column.
-- 'answered'  the model answered with at least one valid citation;
-- 'refused'   no valid citation (the refusal path, invariant 9) or nothing permitted to send;
-- 'truncated' the completion hit the token limit (finish reason 'length'): neither an answer nor a
--             refusal, so refusal rates must not count it (TruncatedCompletion).
-- Judge calls (purpose 'eval_judge') record 'answered' or 'truncated' too.
ALTER TABLE query_log ADD COLUMN outcome TEXT;

UPDATE query_log SET outcome = CASE WHEN refused THEN 'refused' ELSE 'answered' END;

-- Before this migration a truncated generation was stored as a refusal with an empty answer. Two rows
-- match, both at the 700-token limit then in force: id 253 (Phase 2 baseline, q060) and id 462
-- (Phase 3 baseline, q052). Re-classify them; the refused flag follows the outcome.
UPDATE query_log SET outcome = 'truncated', refused = FALSE
WHERE purpose = 'query' AND refused AND answer_raw = '' AND completion_tokens >= 700;

ALTER TABLE query_log
    ALTER COLUMN outcome SET NOT NULL,
    ADD CONSTRAINT query_log_outcome_check CHECK (outcome IN ('answered', 'refused', 'truncated')),
    ADD CONSTRAINT query_log_refused_matches_outcome CHECK (refused = (outcome = 'refused'));

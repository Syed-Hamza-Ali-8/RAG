-- 006_query_log_answer: raw LLM output and the citation-check verdict, so every refusal
-- can be traced to the retriever, the model or the citation check.
-- Stored in the database only; never written to application logs (CLAUDE.md invariant 8).
ALTER TABLE query_log
    ADD COLUMN answer_raw         TEXT,   -- exact LLM output; NULL when no LLM call was made
    ADD COLUMN citations_valid    INT,    -- distinct valid source labels cited; NULL when no LLM call
    ADD COLUMN citations_rejected INT;    -- cited labels outside the retrieved set; NULL when no LLM call

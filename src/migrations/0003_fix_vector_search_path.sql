-- Allow pgvector aggregates (avg, sum, etc.) to resolve inside the API-facing
-- functions that operate on vector columns.
--
-- 0002_security_hardening.sql pinned `search_path = public, pg_temp` on every
-- API function. That is safe for the metadata-only functions, but it breaks
-- get_hidden_gems and get_visual_recommendations: both call `avg(embedding)`
-- on a pgvector column, and the `avg(vector)` aggregate lives in the
-- `extensions` schema. Without `extensions` on the search_path Postgres errors
-- with: `function avg(extensions.vector) does not exist`.
--
-- Adding `extensions` to the path for ONLY the two vector-using functions is
-- the minimum change needed. The metadata-only functions keep the tighter
-- path from 0002.

alter function public.get_hidden_gems(bigint, integer)
    set search_path = public, extensions, pg_temp;

alter function public.get_visual_recommendations(bigint, integer)
    set search_path = public, extensions, pg_temp;

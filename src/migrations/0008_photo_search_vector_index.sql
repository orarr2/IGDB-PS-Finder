-- Photo search was timing out (57014) for real users: the PWA calls
-- match_games_by_clip_oss as the anon role, which was capped at
-- statement_timeout = 3s. game_clip_oss had no vector index, so the
-- ORDER BY embedding <=> query LIMIT 800 candidate pass seq-scanned and
-- detoasted all ~19k 512-d vectors: measured 2.8s warm-cache, worse cold ->
-- canceled. (Testing as postgres has no 3s cap, which is how it slipped by.)
--
-- Fix, same as 0007 did for hidden gems: give the ANN scan an HNSW index.
--
-- Subtlety: an HNSW index scan returns at most hnsw.ef_search rows (default
-- 40). The photo-search functions want 800 candidates, so each pins
-- ef_search to its LIMIT - otherwise the index would silently shrink the
-- candidate pool and degrade result quality.
--
-- Measured after: candidate pass 62 ms warm (was 2,787 ms), full function
-- ~0.7s end-to-end.

set maintenance_work_mem = '96MB';  -- speed up the one-time graph build

create index if not exists game_clip_oss_hnsw
  on public.game_clip_oss using hnsw (embedding extensions.vector_cosine_ops);

reset maintenance_work_mem;

alter function public.match_games_by_clip_oss(text, integer) set hnsw.ef_search = 800;
alter function public.match_games_by_clip(text, integer)     set hnsw.ef_search = 800;

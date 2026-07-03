-- Calibrate hidden gems for the HNSW-index era.
--
-- Raising the candidate window too high backfires: at LIMIT 1000 (~9% of the
-- 768-d table) the planner abandons the HNSW index for a seq scan it thinks
-- is cheap - in reality ~2.7s of detoasting, over the anon statement
-- timeout. At LIMIT 400 / ef_search 400 the planner stays on the index:
-- ~10 ms warm. 400 nearest screenshots still cover well over a hundred
-- distinct games before the <25-reviews filter, plenty to fill 12 gems.
--
-- Two quirks worth remembering:
--   * supautils rejects SET hnsw.ef_search inside CREATE FUNCTION but allows
--     it via ALTER FUNCTION - hence the two-step below.
--   * hnsw.ef_search is a placeholder GUC until the pgvector library is
--     loaded in the session; the no-op vector cast forces the load so the
--     ALTER doesn't fail with 42501.

select '[1]'::extensions.vector(1);

create or replace function public.get_hidden_gems(source_id bigint, lim integer default 12)
returns setof games
language sql
stable
set search_path to 'public', 'extensions', 'pg_temp'
as $function$
  with src as (
    select avg(embedding) as v
    from public.game_clip_embeddings
    where game_id = source_id
  ),
  cand as (
    select e.game_id, e.embedding <=> (select v from src) as d
    from public.game_clip_embeddings e
    where e.game_id <> source_id
    order by e.embedding <=> (select v from src)
    limit 400
  ),
  per_game as (
    select game_id, min(d) as d from cand group by game_id
  )
  select g.*
  from public.games g
  join per_game pg on pg.game_id = g.id
  where coalesce(g.total_rating_count, 0) < 25
  order by pg.d
  limit lim;
$function$;

alter function public.get_hidden_gems(bigint, integer) set hnsw.ef_search = 400;

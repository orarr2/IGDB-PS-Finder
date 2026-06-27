-- get_hidden_gems was timing out (statement_timeout, 57014) because the inner
-- query compared every screenshot of every game to the source's average
-- embedding without using the pgvector index. The full-table scan exceeded
-- statement_timeout for any real source game.
--
-- Rewrite: take the 1000 nearest screenshots first (the ORDER BY ... LIMIT
-- against `<=>` uses the index), then aggregate per game and filter to
-- under-the-radar titles (fewer than 25 reviews).

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
    limit 1000
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

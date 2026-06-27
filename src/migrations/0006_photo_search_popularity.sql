-- Photo search: bias toward popular / well-rated games.
--
-- A photo of a real soccer match was returning "Active Soccer 2 DX" (rating
-- 40, 5 reviews) as the source game, because its cover happens to be visually
-- close. The "Smart" tab then chained from that broken source and produced
-- Fighting / Racing games for a football query. Adding a popularity penalty
-- to the distance score makes well-reviewed FIFA / PES titles win when the
-- visual similarity is comparable.
--
-- Penalty scale (added to cosine distance, where 0 = identical, ~1 = unrelated):
--   <5  reviews: +0.30   (essentially demotes the game out of top results)
--   <15 reviews: +0.15
--   <50 reviews: +0.05
--   else:          0
--
-- Also +0.15 for total_rating < 55 (clearly bad).
--
-- The widened candidate window (limit 800 instead of 400) gives popular games
-- a fairer chance to enter the consideration set before the rerank.

create or replace function public.match_games_by_clip_oss(query text, lim integer default 12)
returns setof games
language sql
stable
set search_path to 'public', 'extensions'
as $function$
  with q as (select (query)::extensions.vector(512) as v),
  cand as (
    select e.game_id, e.embedding <=> (select v from q) as d
    from public.game_clip_oss e
    order by e.embedding <=> (select v from q)
    limit 800
  ),
  per_game as (select game_id, min(d) as d from cand group by game_id),
  j as (
    select g.id, g.genres, g.total_rating, g.total_rating_count, pg.d,
      btrim(lower(regexp_replace(g.name,
        '\s*[:\-–]?\s*(digital deluxe|deluxe|ultimate|definitive|complete|game of the year|goty|gold|legendary|standard|champions|anniversary)( edition)?\s*$',
        '', 'i'))) as base
    from per_game pg join public.games g on g.id = pg.game_id
  ),
  consensus as (
    select genre from (
      select unnest(genres) as genre from (select genres, d from j order by d limit 20) t0
    ) t group by genre order by count(*) desc limit 1
  ),
  scored as (
    select id, base,
      d
      - (case when (select genre from consensus) = any(genres) then 0.03 else 0 end)
      + (case
           when coalesce(total_rating_count, 0) < 5  then 0.30
           when coalesce(total_rating_count, 0) < 15 then 0.15
           when coalesce(total_rating_count, 0) < 50 then 0.05
           else 0
         end)
      + (case when coalesce(total_rating, 70) < 55 then 0.15 else 0 end)
      as score
    from j
  ),
  best as (
    select distinct on (base) id, score from scored order by base, score
  )
  select g.* from public.games g join best on best.id = g.id
  order by best.score
  limit lim;
$function$;

-- Same treatment for the Jina-CLIP variant, for parity if it becomes the
-- active photo-search backend again.
create or replace function public.match_games_by_clip(query text, lim integer default 12)
returns setof games
language sql
stable
set search_path to 'public', 'extensions'
as $function$
  with q as (select (query)::extensions.vector(768) as v),
  cand as (
    select e.game_id, e.embedding <=> (select v from q) as d
    from public.game_clip_embeddings e
    order by e.embedding <=> (select v from q)
    limit 800
  ),
  per_game as (select game_id, min(d) as d from cand group by game_id),
  j as (
    select g.id, g.genres, g.total_rating, g.total_rating_count, pg.d,
      btrim(lower(regexp_replace(g.name,
        '\s*[:\-–]?\s*(digital deluxe|deluxe|ultimate|definitive|complete|game of the year|goty|gold|legendary|standard|champions|anniversary)( edition)?\s*$',
        '', 'i'))) as base
    from per_game pg join public.games g on g.id = pg.game_id
  ),
  consensus as (
    select genre from (
      select unnest(genres) as genre from (select genres, d from j order by d limit 20) t0
    ) t group by genre order by count(*) desc limit 1
  ),
  scored as (
    select id, base,
      d
      - (case when (select genre from consensus) = any(genres) then 0.03 else 0 end)
      + (case
           when coalesce(total_rating_count, 0) < 5  then 0.30
           when coalesce(total_rating_count, 0) < 15 then 0.15
           when coalesce(total_rating_count, 0) < 50 then 0.05
           else 0
         end)
      + (case when coalesce(total_rating, 70) < 55 then 0.15 else 0 end)
      as score
    from j
  ),
  best as (
    select distinct on (base) id, score from scored order by base, score
  )
  select g.* from public.games g join best on best.id = g.id
  order by best.score
  limit lim;
$function$;

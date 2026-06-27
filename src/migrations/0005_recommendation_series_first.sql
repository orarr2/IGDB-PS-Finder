-- Rework get_recommendations to lead with series / studio matches.
--
-- 0004 still let IGDB's `similar_games` boost overpower everything: feeding
-- Hades returned Marvel's Spider-Man at #1 (popular AAA in Hades's IGDB
-- similar list) while Hades II sat at #8. Persona 5 Royal returned Borderlands
-- 3 first and the real Persona games at the bottom. Final Fantasy XVI did the
-- same with Borderlands 3.
--
-- Root cause: the franchises and collections columns on `games` were never
-- consulted, and similar_games got a flat +500 just for being in the list.
--
-- This version:
--   * Adds franchises and collections to the join, with heavy weight (80 each).
--   * Adds a small +40 per shared developer.
--   * Floor accepts a franchise OR collection OR developer match outright;
--     otherwise needs real tag overlap (>=2 genres, or genre+theme).
--   * IGDB editorial boost ONLY applies when paired with a real studio or
--     series match. A bare similar_games hit with no dev/franchise/collection
--     link gets zero boost - it can still appear via tag overlap but has to
--     compete on quality and popularity.
--   * Keeps the rating floor (>=55), the rating-weighted score (rating/5),
--     the log-scaled popularity tiebreaker, and the -50 penalty for <65.
--
-- Run order in the dashboard: 0001 -> 0002 -> 0003 -> 0004 -> this.

create or replace function public.get_recommendations(source_id bigint, lim integer default 9)
returns setof games
language sql
stable
set search_path to 'public', 'pg_temp'
as $function$
  with src as (
    select id, genres, themes, game_modes, similar_games, developers,
           franchises, collections
    from public.games where id = source_id
  )
  select g.*
  from public.games g, src,
       lateral (select
         cardinality(array(select unnest(g.genres)      intersect select unnest(src.genres)))      as gov,
         cardinality(array(select unnest(g.themes)      intersect select unnest(src.themes)))      as tov,
         cardinality(array(select unnest(g.game_modes)  intersect select unnest(src.game_modes)))  as mov,
         cardinality(array(select unnest(g.developers)  intersect select unnest(src.developers)))  as dov,
         cardinality(array(select unnest(g.franchises)  intersect select unnest(src.franchises)))  as fov,
         cardinality(array(select unnest(g.collections) intersect select unnest(src.collections))) as cov,
         (g.id = any(src.similar_games)) as is_sim
       ) ov
  where g.id <> src.id
    and coalesce(g.total_rating, 70) >= 55
    and (
         ov.fov >= 1
      or ov.cov >= 1
      or ov.dov >= 1
      or ov.gov >= 2
      or (ov.gov >= 1 and ov.tov >= 1)
      or (ov.is_sim
          and coalesce(g.total_rating, 70) >= 70
          and coalesce(g.total_rating_count, 0) >= 15
          and ov.gov >= 1)
    )
  order by
    ov.fov * 80
    + ov.cov * 80
    + ov.dov * 40
    + (case
         when ov.is_sim and (ov.dov + ov.fov + ov.cov) >= 1
              and coalesce(g.total_rating, 70) >= 80 then 500
         when ov.is_sim and (ov.dov + ov.fov + ov.cov) >= 1
              and coalesce(g.total_rating, 70) >= 70 then 200
         else                                                  0
       end)
    + ov.gov * 10
    + ov.tov *  5
    + ov.mov *  3
    + coalesce(g.total_rating, 0) / 5
    + ln(greatest(coalesce(g.total_rating_count, 0), 1) + 1) * 1.5
    - (case when coalesce(g.total_rating, 70) < 65 then 50 else 0 end)
    desc,
    g.total_rating_count desc nulls last,
    g.total_rating desc nulls last
  limit lim;
$function$;

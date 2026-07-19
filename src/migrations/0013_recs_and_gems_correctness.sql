-- Two correctness bugs the audit surfaced. Both are ranking, not schema.
--
-- 1) get_recommendations: coalesce(total_rating, 70) treated an unrated game
--    as an assumed 70/100, which cleared the >=55 floor AND dodged the <65
--    penalty. Since the collector deliberately keeps upcoming/unreleased
--    titles (they need to appear in "Upcoming"), this meant an unreleased
--    game could surface in Smart recommendations with a phantom score.
--
--    Fix: require a real total_rating >= 55, AND exclude games that haven't
--    shipped yet (they belong to the Upcoming feed, not Smart recs). This
--    also cleanly drops the 342 no-rating rows from Smart's candidate pool
--    (they can still be found via search / Upcoming / photo).
--
--    Editions/re-releases duplication and the 2,662 tag-less games are NOT
--    fixed here - those get their own migration in Stage 4 so their impact
--    is measured independently.
--
-- 2) get_hidden_gems had no rating floor at all - a game could be a "gem"
--    with rating 40. The docstring in the app promises "highly rated but
--    low-popularity"; enforce that.
--
-- Both live functions keep their tuned parameters (0005/0009).

-- ----- get_recommendations: real rating + not-yet-released filter ----------
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
    -- CHANGED: real rating required (was coalesce(...,70) >= 55)
    and g.total_rating is not null
    and g.total_rating >= 55
    -- CHANGED: no unreleased games (they belong to Upcoming, not Smart)
    and (g.release_date is null or g.release_date <= now())
    and (
         ov.fov >= 1
      or ov.cov >= 1
      or ov.dov >= 1
      or ov.gov >= 2
      or (ov.gov >= 1 and ov.tov >= 1)
      or (ov.is_sim
          and g.total_rating >= 70
          and coalesce(g.total_rating_count, 0) >= 15
          and ov.gov >= 1)
    )
  order by
    ov.fov * 80
    + ov.cov * 80
    + ov.dov * 40
    + (case
         when ov.is_sim and (ov.dov + ov.fov + ov.cov) >= 1
              and g.total_rating >= 80 then 500
         when ov.is_sim and (ov.dov + ov.fov + ov.cov) >= 1
              and g.total_rating >= 70 then 200
         else                                                  0
       end)
    + ov.gov * 10
    + ov.tov *  5
    + ov.mov *  3
    + g.total_rating / 5
    + ln(greatest(coalesce(g.total_rating_count, 0), 1) + 1) * 1.5
    - (case when g.total_rating < 65 then 50 else 0 end)
    desc,
    g.total_rating_count desc nulls last,
    g.total_rating desc nulls last
  limit lim;
$function$;

-- ----- get_hidden_gems: quality floor + unreleased filter ------------------
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
    -- CHANGED: quality floor (was no floor at all - rating-40 titles slipped through)
    and g.total_rating is not null
    and g.total_rating >= 60
    -- CHANGED: no unreleased "gems"
    and (g.release_date is null or g.release_date <= now())
  order by pg.d
  limit lim;
$function$;

alter function public.get_hidden_gems(bigint, integer) set hnsw.ef_search = 400;

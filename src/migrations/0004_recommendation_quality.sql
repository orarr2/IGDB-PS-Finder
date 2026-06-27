-- Rework get_recommendations scoring so it stops surfacing junk.
--
-- The original scorer (in collect_igdb.py's docstring) was:
--   +1000 if in similar_games  + 15/dev + 10/genre + 5/theme + 3/mode + rating/20
--
-- Two failure modes in practice:
--   1. similar_games (IGDB editorial) is noisy: feeding F1 2021 returned
--      MotoGP 19 (rating 39) and FIA European Truck Racing (rating 55) only
--      because IGDB had them in F1 2021's similar list.
--   2. Almost zero weight on review count, so a hugely-reviewed AAA could be
--      tied with a 4-rating obscurity that happened to share a genre.
--
-- This version:
--   * Requires either an IGDB-curated pick that is *also* decently reviewed,
--     OR at least 2 shared tags. No more 1-shared-genre noise.
--   * Hard floor at total_rating >= 55 - we never recommend an outright bad
--     game, even from the IGDB list.
--   * Tiered editorial boost: 600 if curated and well-rated, 350 if curated
--     and ok-rated, 50 if curated but low-rated.
--   * Quality weight doubled (rating/5), and popularity added as a log-scaled
--     tiebreaker so AAA titles edge out obscure ones with similar tag overlap.
--   * -40 penalty for total_rating < 65 to push borderline picks down.
--
-- Run order in the dashboard: 0001 → 0002 → 0003 → this.

create or replace function public.get_recommendations(source_id bigint, lim integer default 9)
returns setof games
language sql
stable
set search_path to 'public', 'pg_temp'
as $function$
  with src as (
    select id, genres, themes, game_modes, similar_games, developers
    from public.games where id = source_id
  )
  select g.*
  from public.games g, src
  where g.id <> src.id
    -- relevance floor
    and (
      (g.id = any(src.similar_games)
        and coalesce(g.total_rating, 70) >= 65
        and coalesce(g.total_rating_count, 0) >= 10)
      or (
        cardinality(array(select unnest(g.genres)     intersect select unnest(src.genres))) +
        cardinality(array(select unnest(g.themes)     intersect select unnest(src.themes))) +
        cardinality(array(select unnest(g.game_modes) intersect select unnest(src.game_modes))) +
        cardinality(array(select unnest(g.developers) intersect select unnest(src.developers)))
      ) >= 2
    )
    -- popularity floor for non-curated picks
    and (g.id = any(src.similar_games) or coalesce(g.total_rating_count, 0) >= 10)
    -- never recommend outright bad games
    and coalesce(g.total_rating, 70) >= 55
  order by
    (case
       when g.id = any(src.similar_games) and coalesce(g.total_rating, 70) >= 75 then 600
       when g.id = any(src.similar_games) and coalesce(g.total_rating, 70) >= 65 then 350
       when g.id = any(src.similar_games)                                        then  50
       else                                                                              0
     end)
    + cardinality(array(select unnest(g.genres)     intersect select unnest(src.genres)))     * 10
    + cardinality(array(select unnest(g.themes)     intersect select unnest(src.themes)))     *  5
    + cardinality(array(select unnest(g.game_modes) intersect select unnest(src.game_modes))) *  3
    + cardinality(array(select unnest(g.developers) intersect select unnest(src.developers))) * 15
    + coalesce(g.total_rating, 0) / 5
    + ln(greatest(coalesce(g.total_rating_count, 0), 1) + 1) * 2.5
    - (case when coalesce(g.total_rating, 70) < 65 then 40 else 0 end)
    desc,
    g.total_rating_count desc nulls last,
    g.total_rating desc nulls last
  limit lim;
$function$;

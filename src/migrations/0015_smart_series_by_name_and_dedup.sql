-- Two independent quality upgrades to get_recommendations, both surfaced by
-- the DB audit:
--
-- 1) 2,662 games (37.5% of the catalog) have neither an IGDB franchise nor
--    a collection tag. The current engine's series-first ranking can't help
--    them at all - a "Ratchet & Clank" entry with no collection tag has no
--    series signal to boost its siblings. The app.js "More from this series"
--    row already uses base-name matching to catch these, but that's a
--    separate row; the main Smart ranking has been blind to it.
--
--    Fix: derive a base_name in-query (strip common edition/subtitle noise)
--    and grant a smaller boost when the candidate's base_name equals the
--    source's base_name. Weight (30) is below franchise/collection (80) but
--    above genre (10), reflecting confidence: a shared base name is a
--    strong signal, but weaker than a curated IGDB tag.
--
-- 2) Edition dedup. 62 base-name groups in the catalog contain 127 games
--    that are re-releases / editions of one another (God of War +
--    "God of War (2018)" is one such group; Deluxe/GOTY are others).
--    Photo search does distinct on (base) already; Smart didn't - meaning
--    a source like "Dark Souls" could return "Dark Souls: Prepare to Die
--    Edition" AND "Dark Souls Remastered" in the same top 12.
--
--    Fix: same distinct-on-base pattern that 0006 uses for photo search.
--    The remaining edition surfaces via search / detail links.
--
-- The relevance floor, the similar_games gating, and the rating/popularity
-- signals from 0005/0013 all carry over unchanged.
--
-- Baseline: eval/results/recs_get_recommendations_baseline_*.json
-- After:    eval/recommendations.py get_recommendations after_series_and_dedup 300

create or replace function public.get_recommendations(source_id bigint, lim integer default 12)
returns setof games
language sql
stable
set search_path to 'public', 'pg_temp'
as $function$
  with src as (
    select id, name, genres, themes, game_modes, similar_games, developers,
           franchises, collections,
      -- Sequential passes: trailing parens -> subtitle after ":" / "-" /
      -- "–" / "(" -> edition suffix -> series number.
      -- Order matters: subtitle strip must run before number strip so
      -- "Uncharted 2: Among Thieves" -> "uncharted 2" -> "uncharted"
      -- (not "uncharted 2" after a single-pass regex). Verified against
      -- 30 real title patterns.
      btrim(lower(
        regexp_replace(
          regexp_replace(
            regexp_replace(
              regexp_replace(name, '\s*\([^)]+\)\s*$', '', 'i'),
              '\s*[:\-–(].*$', '', 'i'),
            '\s+(digital deluxe|deluxe|ultimate|definitive|complete|game of the year|goty|gold|legendary|standard|champions|anniversary|remastered|remaster)( edition)?\s*$', '', 'i'),
          '\s+(i{1,3}|iv|v|vi{0,3}|ix|x|\d+)$', '', 'i')
      )) as base
    from public.games where id = source_id
  ),
  cand as (
    select g.*,
      btrim(lower(regexp_replace(g.name,
        '\s*[:\-–(]\s*.*$|\s+(i{1,3}|iv|v|vi{0,3}|ix|x|\d+)$',
        '', 'i'))) as base
    from public.games g
  ),
  scored as (
    select cand.*,
      cardinality(array(select unnest(cand.genres)      intersect select unnest(src.genres)))      as gov,
      cardinality(array(select unnest(cand.themes)      intersect select unnest(src.themes)))      as tov,
      cardinality(array(select unnest(cand.game_modes)  intersect select unnest(src.game_modes)))  as mov,
      cardinality(array(select unnest(cand.developers)  intersect select unnest(src.developers)))  as dov,
      cardinality(array(select unnest(cand.franchises)  intersect select unnest(src.franchises)))  as fov,
      cardinality(array(select unnest(cand.collections) intersect select unnest(src.collections))) as cov,
      (cand.id = any(src.similar_games)) as is_sim,
      -- Name-based series signal: same normalized base, meaningful base
      -- length so a two-letter fragment doesn't cluster the world.
      (cand.base = src.base
        and cand.base <> ''
        and length(src.base) >= 4
        and cand.id <> src.id) as name_sib
    from cand, src
    where cand.id <> src.id
      and cand.total_rating is not null
      and cand.total_rating >= 55
      and (cand.release_date is null or cand.release_date <= now())
  ),
  gated as (
    select *
    from scored
    where
         fov >= 1
      or cov >= 1
      or dov >= 1
      or name_sib
      or gov >= 2
      or (gov >= 1 and tov >= 1)
      or (is_sim
          and total_rating >= 70
          and coalesce(total_rating_count, 0) >= 15
          and gov >= 1)
  ),
  computed as (
    select
      id, name, base,
      fov * 80
      + cov * 80
      + dov * 40
      + (case when name_sib then 30 else 0 end)
      + (case
           when is_sim and (dov + fov + cov) >= 1
                and total_rating >= 80 then 500
           when is_sim and (dov + fov + cov) >= 1
                and total_rating >= 70 then 200
           else                                                  0
         end)
      + gov * 10
      + tov *  5
      + mov *  3
      + total_rating / 5
      + ln(greatest(coalesce(total_rating_count, 0), 1) + 1) * 1.5
      - (case when total_rating < 65 then 50 else 0 end) as score,
      total_rating_count, total_rating
    from gated
  ),
  best as (
    select distinct on (base) id, score, total_rating_count, total_rating
    from computed
    order by base, score desc
  )
  select g.*
  from public.games g join best on best.id = g.id
  order by
    best.score desc,
    best.total_rating_count desc nulls last,
    best.total_rating desc nulls last
  limit lim;
$function$;

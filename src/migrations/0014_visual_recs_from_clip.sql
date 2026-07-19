-- Rebuild "Looks alike" (get_visual_recommendations) on top of the CLIP
-- embeddings (game_clip_oss, 512-d), replacing the MobileNet-ImageNet
-- pipeline that fed visual_neighbors.
--
-- Why: MobileNet was trained to classify 1000 ImageNet object categories -
-- it answers "what's in the picture" (dog, car, chair), not "does this look
-- like the same kind of game". The eval baseline confirmed the impact:
--
--   MobileNet visual_neighbors  ->  nDCG@12 = 0.082  (barely above chance)
--   Smart metadata engine       ->  nDCG@12 = 0.737  (as reference)
--
-- CLIP ViT-B/32 was trained on 400M image-text pairs and captures scene /
-- style / genre far better. We already have per-screenshot CLIP vectors for
-- 6,594 games in game_clip_oss - the same table the photo search uses -
-- and the HNSW index makes ANN cheap.
--
-- Design mirrors get_hidden_gems (source = avg of the game's shots, then
-- nearest neighbours via HNSW), with two additions from match_games_by_clip:
--
--   * edition dedup (distinct on base_name) so multiple editions of the
--     same title don't stack in the top 12.
--   * popularity floor: no games with fewer than 15 reviews and no games
--     rated below 55 - this is the Looks-alike surface, so we still want
--     recognisable titles rather than obscurities (that's Hidden gems' job).
--
-- Fallback: if a game has no CLIP shots (491 games, mostly PS1/old titles),
-- fall back to the pre-existing visual_neighbors row. Keeps coverage at 100%.
--
-- Baseline is captured in eval/results/recs_get_visual_recommendations_baseline_*.
-- After: eval/recommendations.py get_visual_recommendations after_clip 300

create or replace function public.get_visual_recommendations(source_id bigint, lim integer default 12)
returns setof games
language sql
stable
set search_path to 'public', 'extensions', 'pg_temp'
as $function$
  with src as (
    select avg(embedding) as v
    from public.game_clip_oss
    where game_id = source_id
  ),
  has_clip as (select v is not null as ok from src),
  -- Fast path: we have CLIP shots for the source - do ANN on game_clip_oss.
  cand as (
    select e.game_id, e.embedding <=> (select v from src) as d
    from public.game_clip_oss e
    where (select ok from has_clip)
      and e.game_id <> source_id
    order by e.embedding <=> (select v from src)
    limit 400
  ),
  per_game as (
    select c.game_id, min(c.d) as d
    from cand c
    group by c.game_id
  ),
  scored as (
    select g.id, g.total_rating, g.total_rating_count, pg.d,
      btrim(lower(regexp_replace(g.name,
        '\s*[:\-–]?\s*(digital deluxe|deluxe|ultimate|definitive|complete|game of the year|goty|gold|legendary|standard|champions|anniversary|remastered|remaster)( edition)?\s*$',
        '', 'i'))) as base
    from per_game pg join public.games g on g.id = pg.game_id
    where g.total_rating is not null
      and g.total_rating >= 55
      and coalesce(g.total_rating_count, 0) >= 15
      and (g.release_date is null or g.release_date <= now())
  ),
  best as (
    select distinct on (base) id, d from scored order by base, d
  ),
  clip_out as (
    select g.*
    from public.games g join best on best.id = g.id
    order by best.d
    limit lim
  ),
  -- Fallback path: no CLIP shots for the source - use the older
  -- visual_neighbors table (MobileNet, precomputed). Coverage-first.
  fallback_out as (
    select g.*
    from public.visual_neighbors vn
    cross join lateral unnest(vn.neighbor_ids) with ordinality as n(nid, ord)
    join public.games g on g.id = n.nid
    where not (select ok from has_clip)
      and vn.game_id = source_id
    order by n.ord
    limit lim
  )
  select * from clip_out
  union all
  select * from fallback_out;
$function$;

-- Match the ef_search discipline of the other vector functions so the ANN
-- window is honoured (default is 40, we want the LIMIT 400 candidate pool).
alter function public.get_visual_recommendations(bigint, integer)
  set hnsw.ef_search = 400;

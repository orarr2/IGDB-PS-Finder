-- game_clip_oss got a UNIQUE (game_id, shot_idx) from day one, but
-- game_clip_embeddings never did - which also meant no ON CONFLICT target,
-- so no idempotent loader could exist for the Hidden gems table. Verified
-- before applying: all existing rows are already distinct pairs.
--
-- With this in place, src/ml/load_clip_embeddings.py upserts the computed
-- shards safely (and the "Compute CLIP embeddings" workflow now runs it).

create unique index if not exists game_clip_embeddings_game_shot_key
  on public.game_clip_embeddings (game_id, shot_idx);

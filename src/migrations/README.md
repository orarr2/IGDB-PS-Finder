# Database migrations

Everything the Supabase backend needs, in plain SQL. Apply them **in numeric
order** - paste each file into the dashboard SQL editor (or run
`supabase db push` with the CLI):

```
0000 → 0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010
```

On a **fresh project** start at `0000_baseline.sql`; the live production
project already contains everything, so new changes land as new numbered
files.

| File | What it does |
|---|---|
| `0000_baseline.sql` | The full starting schema, reconstructed from the live project: the `pg_trgm` + `vector` (pgvector) extensions, every table (`games`, `game_clip_oss`, `game_clip_embeddings`, `visual_neighbors`, `user_media`, plus two legacy embedding tables), all indexes (including the HNSW vector index), read-only Row-Level-Security policies, and the base `search_games` / `get_visual_recommendations` / `get_hidden_gems` functions. |
| `0001_api_max_rows.sql` | Caps any single Data API (PostgREST) response at 200 rows - defence-in-depth so no request can ever pull the whole table. |
| `0002_security_hardening.sql` | Pins a fixed `search_path` on all API-facing functions (closes the "role mutable search_path" privilege-escalation lint). |
| `0003_fix_vector_search_path.sql` | Re-adds the `extensions` schema to the search_path of the two vector-using functions, which 0002 broke (`avg(vector)` lives in `extensions`). |
| `0004_recommendation_quality.sql` | First rework of `get_recommendations`: rating floor (≥ 55), tiered boost for IGDB-curated picks, log-scaled popularity tiebreaker, penalty for sub-65 ratings. |
| `0005_recommendation_series_first.sql` | Current `get_recommendations`: same-franchise / same-collection matches lead (+80 each), +40 per shared developer, and the IGDB editorial boost only counts when the game also shares a studio or series. |
| `0006_photo_search_popularity.sql` | Photo search (`match_games_by_clip_oss` / `match_games_by_clip`): adds a popularity penalty to the vector distance so obscure, badly-reviewed titles stop outranking the games people actually play, and widens the candidate window to 800. |
| `0007_hidden_gems_use_vector_index.sql` | Rewrites `get_hidden_gems` to take the nearest screenshots via the HNSW index first, then aggregate - fixes the statement-timeout (error 57014) the full-table scan caused. |
| `0008_photo_search_vector_index.sql` | Adds the missing HNSW index on `game_clip_oss` (photo search seq-scanned ~19k vectors: 2.8s, over the anon timeout) and pins `hnsw.ef_search = 800` on the photo-search functions so the index returns the full candidate window. |
| `0009_hidden_gems_ef_calibration.sql` | Recalibrates hidden gems to LIMIT 400 / `ef_search` 400 - at 1000 the planner fell back to a seq scan and timed out again. Documents two supautils/pgvector quirks. |
| `0010_anon_statement_timeout.sql` | Raises the anon `statement_timeout` from 3s to 8s so the first cold-cache vector query after idle (~4s) succeeds; paired with a one-retry policy in the app. |

## Which function ends up where

Later files replace earlier definitions, so after running everything the live
versions are:

- `search_games`, `get_visual_recommendations` - from **0000**
- `get_recommendations` - from **0005**
- `match_games_by_clip_oss`, `match_games_by_clip` - from **0006** (body) + **0008** (`ef_search`)
- `get_hidden_gems` - from **0009**

## Conventions

- Every function is `stable`, `language sql`, and pins `search_path`
  (`public, pg_temp`, plus `extensions` only where pgvector operators are
  needed).
- All tables have RLS enabled with **read-only** policies for
  `anon` / `authenticated` - that is what makes the publishable key safe to
  ship inside the app. Writes go through the service-role key only (loaders
  and CI), which bypasses RLS.
- Vector work stays index-friendly: `order by embedding <=> query limit n`
  against the raw table *before* any aggregation, so the HNSW index is used
  and queries return in milliseconds instead of timing out.

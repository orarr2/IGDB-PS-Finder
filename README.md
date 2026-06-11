# IGDB PlayStation Game Recommender

A desktop game-recommendation app for PS4/PS5, built on data pulled from the
[IGDB API](https://api-docs.igdb.com/) and served from a Supabase Postgres
database. Type a game you like, see its details, and get nine recommendations
you might enjoy — with cover art, ratings, and a one-click share.

![flow: Home → Detail → Recommendations](docs/flow.png)

## 📱 iPhone app

There's now an installable **iPhone app** in [`docs/`](docs/) — a Progressive
Web App you add to your Home Screen from Safari (no App Store, no Mac, no Xcode).
It talks to the same live backend, so it returns the same real recommendations.
It's served via GitHub Pages (Deploy from a branch → `/docs`). See
[`docs/README.md`](docs/README.md) for the two-minute setup.

## What's in the repo

| File | Purpose |
|---|---|
| `app.py` | PyQt6 desktop app — three screens (Home / Detail / Recommendations) |
| `collect_igdb.py` | One-shot script that pulls PS4/PS5 metadata from IGDB into `games.parquet` |
| `load_to_supabase.py` | Idempotent upsert of `games.parquet` into Supabase `public.games` |
| `igdb_data_collection.ipynb` | Original notebook that also downloads cover/screenshot images for ML work |
| `Launch Recommender.bat` | Double-click launcher on Windows |
| `BUILD_EXE.md` | PyInstaller recipe for a standalone `.exe` |
| `.env.example` | Required environment variables |

## How recommendations work

`get_recommendations(source_id)` is a Postgres function that scores every other
game against the one you picked. The score blends curated similarity with tag
overlap and quality:

- **+1000** if the candidate appears in IGDB's curated `similar_games` for the
  source
- **+15** per shared developer
- **+10** per shared genre
- **+5** per shared theme
- **+3** per shared `game_mode`
- **+ rating/20** mild quality boost

Top-9 by score wins. Results are produced server-side in one round-trip.

## Setup

### 1. Supabase project

1. Create a Supabase project (any region).
2. Apply the migrations in `migrations/` (or just paste the SQL from
   `collect_igdb.py`'s docstring into the SQL editor — schema is one `games`
   table plus two RPC functions, `search_games` and `get_recommendations`).
3. From **Project Settings → API Keys**, copy:
   - `URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY` (for the one-time load, never
     ship to clients)
   - `anon` / `publishable` key → `SUPABASE_ANON_KEY` (used by the app)

### 2. Twitch developer app (for IGDB)

Register an app at https://dev.twitch.tv/console/apps. Copy the Client ID and
Client Secret into your `.env`.

### 3. Local config

```bash
cp .env.example .env
# fill in the four/five values
```

### 4. Load the dataset (one time)

```bash
pip install -r requirements.txt  # or: pip install requests pandas tqdm pyarrow supabase PyQt6
python collect_igdb.py            # ~20 seconds, writes igdb_dataset/data/games.parquet
python load_to_supabase.py        # ~10 seconds, upserts 3,840 rows
```

### 5. Run the app

```bash
python app.py
```

Or double-click **`Launch Recommender.bat`** on Windows — it installs deps and
loads `.env` automatically.

## Building a standalone `.exe`

See [`BUILD_EXE.md`](BUILD_EXE.md). The short version:

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name PSGameRecommender `
    --hidden-import=supabase --hidden-import=postgrest --hidden-import=gotrue `
    --hidden-import=storage3 --hidden-import=realtime --hidden-import=supafunc `
    app.py
```

## Notes

- **Images are not stored in the DB.** Covers and screenshots are served from
  IGDB's CDN at `https://images.igdb.com/igdb/image/upload/t_<size>/<image_id>.jpg`.
  The DB only stores the `image_id`. This keeps the dataset under 100 MB.
- **Row-Level Security is on.** The `games` table allows anonymous reads (so
  the publishable key works in the client) but blocks writes from anyone except
  the service-role.
- **The recommendation engine is SQL-based**, not the gradient-boosting model
  the repo name hints at. That model is a planned next step — bring your own
  CNN on the cover images.
- **IGDB API change:** the old `category = 0` filter (main games) no longer
  works; the field was renamed `game_type`. `collect_igdb.py` already uses the
  new name. If you reuse the notebook, patch that line first.

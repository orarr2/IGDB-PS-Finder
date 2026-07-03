# PS Finder - PlayStation game recommender

**Live app: https://orarr2.github.io/IGDB-PS-Finder/**

<p align="center">
  <img src="src/docs/ps-finder-logo.png" alt="PS Finder" width="380">
</p>

Tell it a PlayStation game you love and get real recommendations - ranked by
metadata (**Smart**), by how the gameplay actually *looks* using computer vision
(**Looks alike**), or surfaced as under-the-radar **Hidden gems**. You can also
search by a screenshot, browse **Upcoming** releases, and keep a **My List**.
It covers 7,000+ PS1-PS5 titles from the [IGDB API](https://api-docs.igdb.com/),
served from a Supabase Postgres database.

<p align="center">
  <img src="src/docs/screenshots/search.jpg"           width="24%" alt="Type-ahead search with covers and ratings">
  <img src="src/docs/screenshots/detail.jpg"           width="24%" alt="Game detail - rating, genres, screenshots">
  <img src="src/docs/screenshots/recs-smart.jpg"       width="24%" alt="Smart recommendations - series first">
  <img src="src/docs/screenshots/recs-hidden-gems.jpg" width="24%" alt="Hidden gems - great games with few reviews">
</p>

## Install on iPhone / iPad

PS Finder is a Progressive Web App, so there's no App Store, no Mac and no Xcode:

1. Open the **live app** link above in **Safari** (it has to be Safari on iOS).
2. Tap the **Share** button (the square with an up-arrow, at the bottom of the screen).
3. Scroll down the share sheet and tap **Add to Home Screen**.
4. Tap **Add** (top right).

It now sits on your Home Screen with its own icon and opens full-screen, like a
native app. On **Android**, open the link in Chrome, then use the menu and tap
**Install app** / **Add to Home screen**.

## What it does

- **Three recommendation modes** - Smart (metadata: genres, themes, studio,
  series), Looks alike (computer vision on real gameplay screenshots), and
  Hidden gems (highly rated but obscure).
- **Search by a photo** - upload a screenshot and it finds games that look like
  it, running fully on your device.
- **Upcoming** - the most anticipated titles plus everything releasing in the
  next three months.
- **My List**, cover art, ratings, a screenshot gallery, and one-tap share.

The web/iOS app lives in [`src/docs/`](src/docs/) and is served via GitHub
Pages. A PyQt6 desktop version and the data pipeline are also in this repo
(below).

## What's in the repo

Everything that isn't the README or the `.github/` workflow folder lives
under `src/`:

| Path | Purpose |
|---|---|
| `src/docs/` | Web/iOS PWA (the live app, served via GitHub Pages) |
| `src/desktop_app/` | PyQt6 desktop app + IGDB data pipeline (see [`src/desktop_app/README.md`](src/desktop_app/README.md)) |
| `src/ml/` | Visual-similarity pipeline (CLIP embeddings, neighbours, ONNX export) |
| `src/migrations/` | Supabase SQL migrations - full schema from scratch (see [`src/migrations/README.md`](src/migrations/README.md)) |
| `src/android/` | TWA manifest for the Android APK build |
| `.github/workflows/` | CI: dataset refresh, embedding builds, Pages deploy, APK build |
| `.env.example` | Required environment variables |

## Architecture

```mermaid
flowchart TD
  igdb["IGDB API<br/>(Twitch OAuth)"] -->|"collect_igdb.py"| pq["games.parquet"]
  pq -->|"load_to_supabase.py<br/>(service key)"| g
  cdn["IGDB image CDN"] -->|"gameplay screenshots"| ml["src/ml/ vision pipelines<br/>(GitHub Actions, CPU)"]
  ml -->|"CLIP 512-d"| oss
  ml -->|"jina-clip 768-d"| emb
  ml -->|"CNN nearest neighbours"| vn
  subgraph db["Supabase Postgres + pgvector (RLS: public read-only)"]
    g[("games")]
    oss[("game_clip_oss")]
    emb[("game_clip_embeddings")]
    vn[("visual_neighbors")]
    rpc{{"RPC functions<br/>search_games · get_recommendations ·<br/>get_visual_recommendations · get_hidden_gems ·<br/>match_games_by_clip_oss"}}
  end
  g --> rpc
  oss --> rpc
  emb --> rpc
  vn --> rpc
  rpc -->|"publishable key"| pwa["Web / iOS / Android PWA<br/>src/docs/ on GitHub Pages"]
  rpc -->|"publishable key"| desk["Desktop app<br/>(PyQt6)"]
  photo["Your photo"] -->|"on-device CLIP<br/>(transformers.js)"| pwa
  cdn -.->|"covers & screenshots<br/>at view time"| pwa
```

## How recommendations work

All four engines are Postgres functions, so results come back server-side in
one round-trip. The SQL lives in [`src/migrations/`](src/migrations/) (see its
[README](src/migrations/README.md) for the version history).

**Smart** - `get_recommendations(source_id)` scores every other game against
your pick; the app shows the top 12:

- **Series first:** +80 per shared franchise and +80 per shared collection -
  sequels and same-universe games lead the list.
- **+40** per shared developer.
- IGDB's curated `similar_games` adds **+500** (candidate rated ≥ 80) or
  **+200** (≥ 70), but **only when the game also shares a studio, franchise or
  collection** with your pick. A bare editorial match gets no boost.
- **+10** per shared genre, **+5** per shared theme, **+3** per shared game
  mode.
- Quality and popularity: `rating / 5`, a log-scaled review-count bonus, and
  **-50** if the rating is below 65.
- Hard floors: nothing rated below 55 is ever recommended, and a candidate
  must share a series, studio, or real tag overlap (≥ 2 genres, or genre +
  theme) to qualify at all.

**Looks alike** - `get_visual_recommendations(source_id)` returns the games
whose real gameplay screenshots look closest, from the precomputed
`visual_neighbors` table (CNN embeddings built by `src/ml/visual_similarity.py`).

**Hidden gems** - `get_hidden_gems(source_id)` finds the nearest games in CLIP
screenshot-embedding space with an index-accelerated pgvector scan, keeping
only titles with **fewer than 25 reviews** - discovery without bestseller bias.

**Photo search** - the app embeds your photo **on-device** (CLIP via
transformers.js, no image ever uploaded) and `match_games_by_clip_oss` matches
the vector against ~19,000 gameplay-screenshot embeddings, with a popularity
re-rank so obscure shovelware can't outrank the games people actually play.

## Setup

### 1. Supabase project

1. Create a Supabase project (any region).
2. In the SQL editor, run the files in [`src/migrations/`](src/migrations/)
   **in order, `0000` → `0011`**. `0000_baseline.sql` creates everything from
   scratch - the `pg_trgm` and `vector` (pgvector) extensions, the `games`
   table, the vector tables, indexes, read-only RLS policies and the base RPC
   functions; the later files layer on the current recommendation engines.
   Details per file: [`src/migrations/README.md`](src/migrations/README.md).
3. From **Project Settings → API Keys**, copy:
   - `URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY` (for loading data and CI,
     never ship to clients)
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
pip install requests pandas tqdm pyarrow supabase PyQt6
python src/desktop_app/collect_igdb.py        # ~20 seconds, writes igdb_dataset/data/games.parquet
python src/desktop_app/load_to_supabase.py    # ~10 seconds, upserts the rows
```

### 5. Build the vision data (photo search, Looks alike, Hidden gems)

The three visual features need embeddings. The GitHub Actions workflows build
them for free on CPU runners - set the repository secrets listed in the table
below, then dispatch from the **Actions** tab:

1. **Build CLIP (free / OSS)** - embeds up to 3 screenshots per game with
   `clip-vit-base-patch32` (512-d) straight into the `game_clip_oss` table.
   Powers **photo search**. Resumable - re-dispatch until it reports no work
   left.
2. **Compute visual similarity** - CNN embeddings → nearest neighbours →
   loads the `visual_neighbors` table via `src/ml/load_visual_neighbors.py`.
   Powers **Looks alike**.
3. **Compute CLIP embeddings** - jina-clip-v1 (768-d) per-screenshot vectors,
   committed as JSON under `src/ml/clip_embeddings/` and upserted into the
   `game_clip_embeddings` table by `src/ml/load_clip_embeddings.py`. Powers
   **Hidden gems**.

Everything can also run locally: `pip install -r src/ml/requirements.txt` and
run the same scripts with `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` in the
environment.

### 6. Run the desktop app

```bash
python src/desktop_app/app.py
```

Or double-click **`src/desktop_app/Launch Recommender.bat`** on Windows - it
installs deps and loads `.env` automatically.

## Building a standalone `.exe`

See [`src/desktop_app/BUILD_EXE.md`](src/desktop_app/BUILD_EXE.md).

## Automation (GitHub Actions)

All in [`.github/workflows/`](.github/workflows/). Data-writing workflows need
the `SUPABASE_SERVICE_KEY` repository secret (plus `TWITCH_CLIENT_ID` /
`TWITCH_CLIENT_SECRET` / `SUPABASE_URL` for the collector).

| Workflow | Trigger | What it does |
|---|---|---|
| Collect IGDB & load into Supabase | manual | Refreshes the dataset: `collect_igdb.py` → `games.parquet` → upsert into `games` (updates rows, never deletes) |
| Build CLIP (free / OSS) | manual | Embeds screenshots (512-d) into `game_clip_oss` - **photo search** |
| Compute visual similarity | manual + push to its script | CNN embeddings → `visual_neighbors` table - **Looks alike** |
| Compute CLIP embeddings | manual + push to its script | jina-clip-v1 vectors (768-d) committed to `src/ml/clip_embeddings/` and upserted into `game_clip_embeddings` - **Hidden gems** |
| Rebuild CLIP v2 | manual | jina-clip-v2 (1024-d) re-embed via the edge-function proxy (needs Jina credit) |
| Collect player media | manual + push to its script | Steam/Reddit player screenshots → `user_media` table |
| Build Android APK | manual + push to `src/android/` | Wraps the live PWA into a TWA with Bubblewrap; APK as artifact |
| Keep Supabase awake | every 6 hours (cron) | Pings the Data API **and both vector RPCs** - keeps the project unpaused, keeps the ANN caches from going fully cold, and fails loudly if any user-facing path breaks |
| Deploy app to GitHub Pages | manual | Fallback Actions-based Pages deploy. **Not the live method** - the site is served with "Deploy from a branch" (see below), and dispatching this changes the URL layout |

## Troubleshooting

**The app opens but every search fails ("Network error").**
Free-plan Supabase projects auto-pause after ~7 days without traffic. The
"Keep Supabase awake" workflow prevents that, but if the repo (or the workflow)
was ever disabled, open the Supabase dashboard and hit **Restore project**.
Quick health check:
`curl "$SUPABASE_URL/rest/v1/games?select=id&limit=1" -H "apikey: $SUPABASE_ANON_KEY"`
should return HTTP 200 with one row.

**Search works but a recommendation tab is empty.**
That tab's vector data hasn't been built (Setup step 5). Looks alike reads
`visual_neighbors`, Hidden gems reads `game_clip_embeddings`, photo search
reads `game_clip_oss` - each is filled by its own workflow.

**Photo search hangs the first time.**
The CLIP model (~30 MB) is downloaded to the device on first use and cached
after that. On a slow connection the first photo can take a while; later
searches are fast and even work with spotty connectivity.

**The "Compute visual similarity" workflow fails at the load step.**
The `SUPABASE_SERVICE_KEY` repository secret is missing (Settings → Secrets
and variables → Actions). The compute part runs with the public anon key, but
writing `visual_neighbors` needs the service role.

**The installed home-screen app looks stale after an update.**
The service worker is network-first, so a normal close-and-reopen picks up the
newest build. If it's still stale, remove the icon from the Home Screen and
add it again from Safari/Chrome.

**Rotating the Supabase keys.**
Rotate in **Project Settings → API Keys**, then update `src/docs/config.js`
(publishable key - this is the one clients use) and the GitHub Actions secrets
(service key). Leaking the *publishable* key is not an emergency: RLS limits
it to read-only.

**GitHub Pages shows a 404 or the README instead of the app.**
Settings → Pages must be **Deploy from a branch** / `main` / folder `/`
(root), and both root files must exist: `index.html` (redirects into
`src/docs/`) and `.nojekyll` (serves files as-is).

## Notes

- **Images are not stored in the DB.** Covers and screenshots are served from
  IGDB's CDN at `https://images.igdb.com/igdb/image/upload/t_<size>/<image_id>.jpg`.
  The DB only stores the `image_id`. This keeps the dataset under 100 MB.
- **Row-Level Security is on.** The `games` table allows anonymous reads (so
  the publishable key works in the client) but blocks writes from anyone except
  the service-role.
- **How GitHub Pages serves the app:** Settings → Pages is set to **"Deploy
  from a branch"** (`main`, folder `/`). The root `index.html` redirects the
  canonical URL into `src/docs/`, and the root `.nojekyll` makes Pages serve
  the files as-is. Full instructions in
  [`src/docs/README.md`](src/docs/README.md).
- **The recommendation engine is SQL-based**, not the gradient-boosting model
  the repo name hints at. That model is a planned next step - bring your own
  CNN on the cover images.
- **IGDB API change:** the old `category = 0` filter (main games) no longer
  works; the field was renamed `game_type`.
  `src/desktop_app/collect_igdb.py` is the canonical, up-to-date collector.
  The notebook in `src/desktop_app/` predates the change and is kept for
  reference only - don't run it as-is.

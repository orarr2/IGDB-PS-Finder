"""Collect PS4/PS5 game metadata from IGDB into games.parquet.

Mirrors igdb_data_collection.ipynb Cells 4–9 but reads credentials from env vars
and skips image downloads (not needed for the Supabase load).

Required environment variables:
    TWITCH_CLIENT_ID
    TWITCH_CLIENT_SECRET
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("collect_igdb")

CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

BASE_DIR = Path("igdb_dataset")
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# IGDB platform ids. Default to the full PlayStation family so a game's whole
# series is captured (e.g. Uncharted 1–3 on PS3, not just Uncharted 4 on PS4).
# Override with IGDB_PLATFORMS="48,167" to go back to PS4/PS5 only.
#   7=PS1  8=PS2  9=PS3  38=PSP  46=PS Vita  48=PS4  167=PS5
_DEFAULT_PLATFORMS = "7,8,9,38,46,48,167"
PLATFORMS = [int(x) for x in os.environ.get("IGDB_PLATFORMS", _DEFAULT_PLATFORMS).split(",") if x.strip()]
PLATFORMS_STR = ",".join(map(str, PLATFORMS))

FIELDS = """
    id, name, slug, summary, storyline,
    rating, rating_count, total_rating, total_rating_count,
    aggregated_rating, aggregated_rating_count,
    first_release_date, game_type, status,
    genres.name, themes.name, game_modes.name, player_perspectives.name,
    keywords.name,
    cover.image_id, cover.width, cover.height,
    screenshots.image_id, artworks.image_id,
    involved_companies.company.name, involved_companies.developer, involved_companies.publisher,
    platforms.name, platforms.id,
    similar_games,
    franchises.name, collections.name,
    age_ratings.rating, age_ratings.category,
    game_engines.name,
    videos.video_id
"""


def get_access_token(client_id: str, client_secret: str) -> str:
    r = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    log.info("Got access token (expires in %s s)", data["expires_in"])
    return data["access_token"]


def make_query_fn(headers: dict):
    def igdb_query(endpoint: str, query: str, max_retries: int = 3):
        url = f"https://api.igdb.com/v4/{endpoint}"
        for attempt in range(max_retries):
            try:
                r = requests.post(url, headers=headers, data=query, timeout=30)
                if r.status_code == 429:
                    wait = 2 ** attempt
                    log.warning("Rate limited, sleeping %ss", wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                log.error("Attempt %s failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        return []
    return igdb_query


def collect_games(igdb_query, batch_size: int = 500, save_every: int = 10) -> list[dict]:
    progress_file = DATA_DIR / "collection_progress.json"
    games_file = DATA_DIR / "games_raw.json"

    if progress_file.exists():
        with open(progress_file) as f:
            progress = json.load(f)
        offset = progress["next_offset"]
        log.info("Resuming from offset %s", offset)
        with open(games_file) as f:
            all_games = json.load(f)
    else:
        offset = 0
        all_games = []

    pbar = tqdm(desc="Collecting games", unit=" games")
    pbar.update(len(all_games))

    batch_num = 0
    while True:
        query = f"""
        fields {FIELDS};
        where platforms = ({PLATFORMS_STR})
            & total_rating_count > 3
            & cover != null
            & game_type = 0;
        limit {batch_size};
        offset {offset};
        sort first_release_date asc;
        """
        try:
            batch = igdb_query("games", query)
        except Exception as e:
            log.error("Failed at offset %s: %s", offset, e)
            break

        if not batch:
            log.info("No more games")
            break

        all_games.extend(batch)
        pbar.update(len(batch))
        offset += batch_size
        batch_num += 1

        if batch_num % save_every == 0:
            with open(games_file, "w") as f:
                json.dump(all_games, f)
            with open(progress_file, "w") as f:
                json.dump({"next_offset": offset}, f)
            log.info("Checkpoint: %s games saved", len(all_games))

        time.sleep(0.35)  # rate limit: 4 req/s

    pbar.close()

    with open(games_file, "w") as f:
        json.dump(all_games, f)
    progress_file.unlink(missing_ok=True)
    log.info("Collection complete. Total: %s", len(all_games))
    return all_games


def normalize_games(games: list[dict]) -> pd.DataFrame:
    rows = []
    for g in games:
        genres = [x["name"] for x in g.get("genres", [])]
        themes = [x["name"] for x in g.get("themes", [])]
        modes = [x["name"] for x in g.get("game_modes", [])]
        perspectives = [x["name"] for x in g.get("player_perspectives", [])]
        keywords = [x["name"] for x in g.get("keywords", [])]

        developers, publishers = [], []
        for ic in g.get("involved_companies", []):
            cname = ic.get("company", {}).get("name", "")
            if ic.get("developer"):
                developers.append(cname)
            if ic.get("publisher"):
                publishers.append(cname)

        platforms = [x["name"] for x in g.get("platforms", [])]
        platform_ids = [x["id"] for x in g.get("platforms", [])]

        cover_id = g.get("cover", {}).get("image_id") if g.get("cover") else None
        screenshot_ids = [s["image_id"] for s in g.get("screenshots", [])]
        artwork_ids = [a["image_id"] for a in g.get("artworks", [])]

        release_date = None
        if g.get("first_release_date"):
            release_date = datetime.fromtimestamp(g["first_release_date"])

        rating = g.get("total_rating")
        rating_count = g.get("total_rating_count", 0)
        weighted = rating * math.log1p(rating_count) / 10 if (rating and rating_count) else None

        rows.append({
            "id": g["id"],
            "name": g.get("name"),
            "slug": g.get("slug"),
            "summary": g.get("summary"),
            "storyline": g.get("storyline"),
            "release_date": release_date,
            "release_year": release_date.year if release_date else None,
            "rating": g.get("rating"),
            "rating_count": g.get("rating_count", 0),
            "total_rating": g.get("total_rating"),
            "total_rating_count": g.get("total_rating_count", 0),
            "aggregated_rating": g.get("aggregated_rating"),
            "aggregated_rating_count": g.get("aggregated_rating_count", 0),
            "weighted_score": weighted,
            "genres": genres,
            "themes": themes,
            "game_modes": modes,
            "player_perspectives": perspectives,
            "keywords": keywords[:20],
            "developers": developers,
            "publishers": publishers,
            "platforms": platforms,
            "platform_ids": platform_ids,
            "on_ps5": 167 in platform_ids,
            "on_ps4": 48 in platform_ids,
            "cover_id": cover_id,
            "screenshot_ids": screenshot_ids,
            "artwork_ids": artwork_ids,
            "num_screenshots": len(screenshot_ids),
            "similar_games": g.get("similar_games", []),
            "franchises": [f["name"] for f in g.get("franchises", [])],
            "collections": [c["name"] for c in g.get("collections", [])],
        })
    return pd.DataFrame(rows)


def main() -> int:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET", file=sys.stderr)
        return 2

    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    igdb_query = make_query_fn(headers)

    # Smoke test
    sample = igdb_query("games", "fields name, rating; where total_rating_count > 100; limit 3;")
    log.info("Smoke test ok: %s", [s.get("name") for s in sample])

    games = collect_games(igdb_query)
    df = normalize_games(games)

    parquet_path = DATA_DIR / "games.parquet"
    csv_path = DATA_DIR / "games.csv"
    df.to_parquet(parquet_path)
    df.to_csv(csv_path, index=False)
    log.info("Wrote %s (%s rows, %s cols)", parquet_path, len(df), len(df.columns))

    print()
    print(f"  rows                 : {len(df):,}")
    print(f"  with cover           : {df['cover_id'].notna().sum():,}")
    print(f"  with rating          : {df['total_rating'].notna().sum():,}")
    print(f"  avg screenshots/game : {df['num_screenshots'].mean():.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Upsert src/ml/clip_embeddings/clip_*.json into `game_clip_embeddings`.

clip_embeddings.py only writes the JSON shards; this loads them into the
table Hidden gems actually reads (get_hidden_gems). Idempotent and
incremental: rows already present in the table (same game_id + shot_idx)
are skipped, the rest are upserted.

Batches are deliberately small: every inserted row also inserts a node into
the HNSW index, so a 200-row statement blows through the API's 8s statement
timeout (57014). 40 rows lands well under it; if a batch still times out it
falls back to loading that batch row by row.

Required environment variables:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   service_role key (writes bypass RLS)

Optional:
    CLIP_DIR   directory with the shards (default src/ml/clip_embeddings)
    LIMIT      stop after this many new rows - smoke-test runs (default 0 = all)
"""

from __future__ import annotations

import glob
import json
import os
import sys

import requests
from postgrest.exceptions import APIError
from supabase import create_client

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
CLIP_DIR = os.environ.get("CLIP_DIR", "src/ml/clip_embeddings")
LIMIT = int(os.environ.get("LIMIT", "0") or 0)

BATCH = 40


def fetch_existing_pairs():
    """(game_id, shot_idx) pairs already in the table. Pages by however many
    rows the server actually returns (PostgREST caps responses at 200)."""
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    pairs, off = set(), 0
    while True:
        rows = requests.get(
            f"{URL}/rest/v1/game_clip_embeddings?select=game_id,shot_idx"
            f"&order=game_id.asc,shot_idx.asc&limit=1000&offset={off}",
            headers=h, timeout=60,
        ).json()
        if not isinstance(rows, list):
            raise RuntimeError(f"REST error while reading coverage: {rows}")
        if not rows:
            return pairs
        pairs.update((r["game_id"], r["shot_idx"]) for r in rows)
        off += len(rows)


def main() -> int:
    if not URL or not KEY:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
        return 2

    shards = sorted(glob.glob(os.path.join(CLIP_DIR, "clip_*.json")))
    if not shards:
        print(f"Nothing to load (no clip_*.json in {CLIP_DIR}).")
        return 0

    existing = fetch_existing_pairs()
    print(f"{len(existing):,} rows already in the table")

    rows = []
    for path in shards:
        with open(path) as f:
            items = json.load(f).get("items", [])
        fresh = [
            {"game_id": int(it["game_id"]), "shot_idx": int(it["shot"]), "embedding": it["v"]}
            for it in items
            if (int(it["game_id"]), int(it["shot"])) not in existing
        ]
        rows.extend(fresh)
        print(f"  read {os.path.basename(path)}: {len(items):,} rows, {len(fresh):,} new")
        if LIMIT and len(rows) >= LIMIT:
            break
    if LIMIT:
        rows = rows[:LIMIT]
    if not rows:
        print("Nothing to load - table already has every shard row.")
        return 0

    sb = create_client(URL, KEY)
    total = len(rows)
    for i in range(0, total, BATCH):
        batch = rows[i : i + BATCH]
        try:
            sb.table("game_clip_embeddings").upsert(
                batch, on_conflict="game_id,shot_idx"
            ).execute()
        except APIError as e:
            if getattr(e, "code", None) != "57014":
                raise
            # HNSW inserts made this batch too slow - load it row by row.
            print(f"  batch at {i} hit the statement timeout, retrying row-by-row")
            for row in batch:
                sb.table("game_clip_embeddings").upsert(
                    [row], on_conflict="game_id,shot_idx"
                ).execute()
        done = min(i + BATCH, total)
        if done % 1000 < BATCH or done == total:
            print(f"  upserted {done:,}/{total:,}")

    print(f"Done. {total:,} new rows upserted into game_clip_embeddings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

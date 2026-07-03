"""Upsert src/ml/clip_embeddings/clip_*.json into `game_clip_embeddings`.

clip_embeddings.py only writes the JSON shards; this loads them into the
table Hidden gems actually reads (get_hidden_gems). Idempotent: rows are
upserted on (game_id, shot_idx), so re-running after a partial load or a
recompute is safe.

Required environment variables:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   service_role key (writes bypass RLS)

Optional:
    CLIP_DIR   directory with the shards (default src/ml/clip_embeddings)
    LIMIT      stop after this many rows - smoke-test runs (default 0 = all)
"""

from __future__ import annotations

import glob
import json
import os
import sys

from supabase import create_client

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
CLIP_DIR = os.environ.get("CLIP_DIR", "src/ml/clip_embeddings")
LIMIT = int(os.environ.get("LIMIT", "0") or 0)

# 768 floats per row -> keep request bodies around 1-2 MB.
BATCH = 200


def main() -> int:
    if not URL or not KEY:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
        return 2

    shards = sorted(glob.glob(os.path.join(CLIP_DIR, "clip_*.json")))
    if not shards:
        print(f"Nothing to load (no clip_*.json in {CLIP_DIR}).")
        return 0

    rows = []
    for path in shards:
        with open(path) as f:
            items = json.load(f).get("items", [])
        rows.extend(
            {"game_id": int(it["game_id"]), "shot_idx": int(it["shot"]), "embedding": it["v"]}
            for it in items
        )
        print(f"  read {os.path.basename(path)}: {len(items):,} rows")
        if LIMIT and len(rows) >= LIMIT:
            break
    if LIMIT:
        rows = rows[:LIMIT]
    if not rows:
        print("Nothing to load (shards are empty).")
        return 0

    sb = create_client(URL, KEY)
    total = len(rows)
    for i in range(0, total, BATCH):
        sb.table("game_clip_embeddings").upsert(
            rows[i : i + BATCH], on_conflict="game_id,shot_idx"
        ).execute()
        done = min(i + BATCH, total)
        if done % 2000 < BATCH or done == total:
            print(f"  upserted {done:,}/{total:,}")

    print(f"Done. {total:,} rows upserted into game_clip_embeddings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

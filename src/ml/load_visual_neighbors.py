"""Upsert ml/visual_neighbors.json into the Supabase `visual_neighbors` table.

visual_similarity.py only writes the JSON; this loads it into the table the app
actually reads (via get_visual_recommendations / fetchVisScores).

Required environment variables:
    SUPABASE_URL
    SUPABASE_SERVICE_KEY   service_role key (writes bypass RLS)

Optional:
    NEIGHBORS_JSON   default src/ml/visual_neighbors.json
"""

from __future__ import annotations

import json
import os
import sys

from supabase import create_client

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
PATH = os.environ.get("NEIGHBORS_JSON", "src/ml/visual_neighbors.json")


def main() -> int:
    if not URL or not KEY:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
        return 2

    data = json.load(open(PATH))
    model = data.get("model")
    neighbors = data.get("neighbors", {})

    rows = [
        {"game_id": int(gid), "neighbor_ids": v["ids"], "scores": v["scores"], "model": model}
        for gid, v in neighbors.items()
    ]
    if not rows:
        print("Nothing to load (no neighbours in JSON).")
        return 0

    sb = create_client(URL, KEY)
    total = len(rows)
    for i in range(0, total, 500):
        sb.table("visual_neighbors").upsert(rows[i : i + 500], on_conflict="game_id").execute()
        print(f"  upserted {min(i + 500, total):,}/{total:,}")

    print(f"Done. {total:,} rows upserted into visual_neighbors (model={model}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Upsert the IGDB PS4/PS5 dataset into Supabase.

Run AFTER igdb_data_collection.ipynb has produced igdb_dataset/data/games.parquet.

Required environment variables:
    SUPABASE_URL          e.g. https://zttqvoqpwtxchxsglard.supabase.co
    SUPABASE_SERVICE_KEY  service_role key (sb_secret_... or JWT)

Optional:
    BATCH_SIZE   default 500
    PARQUET_PATH default igdb_dataset/data/games.parquet
"""

from __future__ import annotations

import math
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
PARQUET_PATH = Path(os.environ.get("PARQUET_PATH", "igdb_dataset/data/games.parquet"))

TABLE = "games"

ARRAY_COLS = {
    "screenshot_ids", "artwork_ids",
    "genres", "themes", "game_modes", "player_perspectives", "keywords",
    "developers", "publishers", "platforms", "platform_ids",
    "franchises", "collections", "similar_games",
}

DROP_COLS = {"num_screenshots"}  # generated column in Postgres


def _clean_scalar(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        if pd.isna(v):
            return None
        return v.isoformat()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _clean_array(v):
    if v is None:
        return []
    if isinstance(v, float) and math.isnan(v):
        return []
    if isinstance(v, np.ndarray):
        v = v.tolist()
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for x in v:
        x = _clean_scalar(x)
        if x is not None:
            out.append(x)
    return out


def to_records(df: pd.DataFrame) -> list[dict]:
    df = df.drop(columns=[c for c in DROP_COLS if c in df.columns], errors="ignore")
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if k in ARRAY_COLS:
                clean[k] = _clean_array(v)
            else:
                clean[k] = _clean_scalar(v)
        records.append(clean)
    return records


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def main() -> int:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY", file=sys.stderr)
        return 2
    if not PARQUET_PATH.exists():
        print(f"ERROR: {PARQUET_PATH} not found — run the notebook first", file=sys.stderr)
        return 2

    print(f"Reading {PARQUET_PATH} ...")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"  {len(df):,} rows, {len(df.columns)} columns")

    records = to_records(df)
    print(f"Cleaned {len(records):,} records")

    sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    total = len(records)
    inserted = 0
    for batch_idx, batch in enumerate(chunked(records, BATCH_SIZE), 1):
        sb.table(TABLE).upsert(batch, on_conflict="id").execute()
        inserted += len(batch)
        print(f"  batch {batch_idx}: upserted {inserted:,}/{total:,}")

    print(f"Done. {inserted:,} rows upserted into public.{TABLE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Embed every game's gameplay screenshots with CLIP (jina-clip-v1) for
semantic photo search. We use Jina's OPEN model here so the vectors match
exactly what the Jina embeddings API returns for an uploaded photo.

Per screenshot (not averaged) → stored in pgvector; a query photo then matches
the single most-similar screenshot of each game ("best scene" retrieval).

Resumable: reads which game_ids already have rows in game_clip_embeddings
(the table Hidden gems queries) and embeds only the games still missing.
Each run writes NEW clip_NN.json shards - existing shards are never touched -
and stops cleanly when TIME_BUDGET_MIN is spent, so the workflow can chain
runs until the whole catalog is covered.

Output: src/ml/clip_embeddings/clip_NN.json shards
        {"items":[{"game_id":id,"shot":idx,"v":[768 floats]}, ...]}

Env: SUPABASE_URL, SUPABASE_KEY (anon; read game list + coverage)
     SHOTS (default 3)  CHUNK (games per batch, default 200)
     LIMIT (max games this run, 0 = all)
     TIME_BUDGET_MIN (default 150; stop flushing cleanly before CI timeout)

Prints a machine-readable line for the CI chain step:
     SUMMARY processed=<games attempted> remaining=<games still uncovered>
"""
from __future__ import annotations

import glob
import io, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image
from transformers import AutoModel

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
SHOTS = int(os.environ.get("SHOTS", "3"))
CHUNK = int(os.environ.get("CHUNK", "200"))
LIMIT = int(os.environ.get("LIMIT", "0"))
TIME_BUDGET = int(os.environ.get("TIME_BUDGET_MIN", "150")) * 60
OUTDIR = "src/ml/clip_embeddings"

IMG = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{}.jpg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def log(*a): print(*a, flush=True)


def rest_paged(query):
    """All rows for a REST query, paging by however many rows the server
    actually returns per request (PostgREST caps responses at 200 rows
    regardless of the limit parameter - see migrations/0001)."""
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    out, off = [], 0
    while True:
        rows = requests.get(
            f"{SUPABASE_URL}/rest/v1/{query}&limit=1000&offset={off}",
            headers=h, timeout=60,
        ).json()
        if not isinstance(rows, list):
            raise RuntimeError(f"REST error for {query}: {rows}")
        if not rows:
            return out
        out.extend(rows)
        off += len(rows)


def fetch_games():
    rows = rest_paged("games?select=id,screenshot_ids&order=id.asc")
    return [g for g in rows if g.get("screenshot_ids")]


def fetch_covered():
    rows = rest_paged("game_clip_embeddings?select=game_id&order=game_id.asc")
    return {r["game_id"] for r in rows}


def next_shard_index():
    taken = [
        int(m.group(1))
        for p in glob.glob(f"{OUTDIR}/clip_*.json")
        if (m := re.search(r"clip_(\d+)\.json$", p))
    ]
    return max(taken) + 1 if taken else 0


def fetch_image(image_id):
    try:
        r = requests.get(IMG.format(image_id), headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def main() -> int:
    t0 = time.time()
    games = fetch_games()
    covered = fetch_covered()
    todo = [g for g in games if g["id"] not in covered]
    uncovered = len(todo)
    if LIMIT:
        todo = todo[:LIMIT]
    log(f"{len(games)} games with screenshots · {len(covered)} already embedded "
        f"· {uncovered} uncovered · doing up to {len(todo)} this run")

    if not todo:
        log("SUMMARY processed=0 remaining=0")
        return 0

    log("Loading jina-clip-v1 …")
    model = AutoModel.from_pretrained("jinaai/jina-clip-v1", trust_remote_code=True)
    model.eval()

    os.makedirs(OUTDIR, exist_ok=True)
    items, shard, written, processed = [], next_shard_index(), 0, 0

    def flush():
        nonlocal items, shard
        if not items:
            return
        p = f"{OUTDIR}/clip_{shard:02d}.json"
        json.dump({"items": items}, open(p, "w"))
        log("wrote", p, len(items))
        items = []
        shard += 1

    for start in range(0, len(todo), CHUNK):
        if time.time() - t0 > TIME_BUDGET:
            log("time budget spent - stopping cleanly, the chain picks up the rest")
            break
        chunk = todo[start:start + CHUNK]
        jobs = []  # (game_id, shot_idx, image_id)
        for g in chunk:
            for idx, sid in enumerate((g["screenshot_ids"] or [])[:SHOTS]):
                jobs.append((g["id"], idx, sid))

        imgs, meta = [], []
        with ThreadPoolExecutor(max_workers=32) as ex:
            for (gid, idx, _sid), im in zip(jobs, ex.map(lambda j: fetch_image(j[2]), jobs)):
                if im is not None:
                    imgs.append(im); meta.append((gid, idx))

        # embed in batches of 64
        for b in range(0, len(imgs), 64):
            batch = imgs[b:b + 64]
            embs = model.encode_image(batch)  # (n,768), L2-normalised by the model
            embs = np.asarray(embs, dtype=np.float32)
            for k, e in enumerate(embs):
                gid, idx = meta[b + k]
                items.append({"game_id": gid, "shot": idx, "v": [round(float(x), 4) for x in e]})
                written += 1
            if len(items) >= 1500:
                flush()
        processed += len(chunk)
        log(f"  {processed}/{len(todo)} games · {written} shots · {time.time()-t0:.0f}s")

    flush()
    log(f"Done: {written} screenshot embeddings for {processed} games in {time.time()-t0:.0f}s")
    log(f"SUMMARY processed={processed} remaining={max(0, uncovered - processed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

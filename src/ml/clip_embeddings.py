"""Embed every game's gameplay screenshots with CLIP (jina-clip-v1) for
semantic photo search. We use Jina's OPEN model here so the vectors match
exactly what the Jina embeddings API returns for an uploaded photo.

Per screenshot (not averaged) → stored in pgvector; a query photo then matches
the single most-similar screenshot of each game ("best scene" retrieval).

Output: src/ml/clip_embeddings/clip_NN.json shards
        {"items":[{"game_id":id,"shot":idx,"v":[768 floats]}, ...]}

Env: SUPABASE_URL, SUPABASE_KEY (anon; read game list)
     SHOTS (default 3)  CHUNK (games per batch, default 200)
"""
from __future__ import annotations

import io, json, os, sys, time
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
OUTDIR = "src/ml/clip_embeddings"

IMG = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{}.jpg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def log(*a): print(*a, flush=True)


def fetch_games():
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    out, off = [], 0
    while True:
        u = f"{SUPABASE_URL}/rest/v1/games?select=id,screenshot_ids&order=id.asc&limit=1000&offset={off}"
        rows = requests.get(u, headers=h, timeout=60).json()
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    out = [g for g in out if g.get("screenshot_ids")]
    return out[:LIMIT] if LIMIT else out


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
    log(f"{len(games)} games with screenshots")

    log("Loading jina-clip-v1 …")
    model = AutoModel.from_pretrained("jinaai/jina-clip-v1", trust_remote_code=True)
    model.eval()

    os.makedirs(OUTDIR, exist_ok=True)
    items, shard, written = [], 0, 0

    def flush():
        nonlocal items, shard
        if not items:
            return
        p = f"{OUTDIR}/clip_{shard:02d}.json"
        json.dump({"items": items}, open(p, "w"))
        log("wrote", p, len(items))
        items = []
        shard += 1

    for start in range(0, len(games), CHUNK):
        chunk = games[start:start + CHUNK]
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
        log(f"  {start + len(chunk)}/{len(games)} games · {written} shots · {time.time()-t0:.0f}s")

    flush()
    log(f"Done: {written} screenshot embeddings in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

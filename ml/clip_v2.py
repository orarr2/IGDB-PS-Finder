"""Rebuild game vectors with jina-clip-v2 (1024-d), via the photo-search Edge
Function's embed-proxy (so the Jina key stays only in the function). Downloads
each screenshot, sends batches to the proxy with concurrency, writes shards.

Output: ml/clip_v2/clip_NN.json  {"items":[{"game_id","shot","v":[1024]}]}

Env: SUPABASE_URL, SUPABASE_KEY (anon), SHOTS (default 4), LIMIT (0=all)
"""
from __future__ import annotations

import base64, io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
PROXY = URL + "/functions/v1/photo-search"
TOKEN = "rebuild-zt-7f3a9"
SHOTS = int(os.environ.get("SHOTS", "4"))
LIMIT = int(os.environ.get("LIMIT", "0"))
BATCH = 12
OUTDIR = "ml/clip_v2"
IMG = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{}.jpg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def log(*a): print(*a, flush=True)


def fetch_games():
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    out, off = [], 0
    while True:
        u = f"{URL}/rest/v1/games?select=id,screenshot_ids&order=id.asc&limit=1000&offset={off}"
        rows = requests.get(u, headers=h, timeout=60).json()
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    out = [g for g in out if g.get("screenshot_ids")]
    return out[:LIMIT] if LIMIT else out


def download(job):
    gid, shot, sid = job
    try:
        r = requests.get(IMG.format(sid), headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 200:
            return None
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((384, 384))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
        return (gid, shot, base64.b64encode(buf.getvalue()).decode())
    except Exception:
        return None


def embed_batch(batch):
    # batch: list of (gid, shot, b64) -> list of (gid, shot, vector)
    for attempt in range(3):
        try:
            r = requests.post(PROXY, timeout=120, json={"embed": [b[2] for b in batch], "token": TOKEN})
            if r.status_code == 200:
                embs = r.json().get("embeddings", [])
                if len(embs) == len(batch):
                    return [(batch[i][0], batch[i][1], embs[i]) for i in range(len(batch))]
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return []


def main() -> int:
    t0 = time.time()
    games = fetch_games()
    jobs = []
    for g in games:
        for idx, sid in enumerate((g["screenshot_ids"] or [])[:SHOTS]):
            jobs.append((g["id"], idx, sid))
    log(f"{len(games)} games, {len(jobs)} screenshots to embed")

    log("Downloading…")
    items = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for r in ex.map(download, jobs):
            if r:
                items.append(r)
    log(f"  downloaded {len(items)} ({time.time()-t0:.0f}s)")

    log("Embedding via proxy…")
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    out, done = [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(embed_batch, batches):
            out.extend(res)
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(batches)} batches · {len(out)} vecs · {time.time()-t0:.0f}s")

    if not out:
        log("ERROR: no embeddings"); return 1

    os.makedirs(OUTDIR, exist_ok=True)
    SH = 1500
    for s in range(0, len(out), SH):
        chunk = out[s:s + SH]
        p = f"{OUTDIR}/clip_{s // SH:02d}.json"
        json.dump({"items": [{"game_id": g, "shot": sh, "v": [round(float(x), 4) for x in v]} for g, sh, v in chunk]}, open(p, "w"))
        log("wrote", p, len(chunk))
    log(f"Done: {len(out)} v2 embeddings in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

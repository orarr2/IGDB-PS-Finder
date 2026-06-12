"""Rebuild game vectors with jina-clip-v2 (1024-d), via the photo-search Edge
Function's embed-proxy (so the embedding key stays only in the function).

Design goals (learned the hard way):
  * Resumable — already-embedded (game_id, shot) pairs are loaded from the
    existing shards and skipped, so a re-run never re-pays for finished work.
  * Checkpointed — every CHECKPOINT successful batches the shards are rewritten
    and committed+pushed, so a job timeout loses at most a few minutes of work
    instead of the whole run. Repeated dispatches converge to 100%.
  * Gentle — low embed concurrency with exponential back-off, because hammering
    the proxy with many parallel batches gets almost everything rate-limited.
  * Honest — prints a clear success ratio so a half-finished run is obvious.

Output: ml/clip_v2/clip_NN.json  {"items":[{"game_id","shot","v":[1024]}]}
Env: SUPABASE_URL, SUPABASE_KEY (anon), SHOTS (default 4), LIMIT (0=all)
"""
from __future__ import annotations

import base64, glob, io, json, os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
PROXY = URL + "/functions/v1/photo-search"
TOKEN = "rebuild-zt-7f3a9"
SHOTS = int(os.environ.get("SHOTS", "4"))
LIMIT = int(os.environ.get("LIMIT", "0"))
BATCH = 8            # images per proxy call (smaller = lighter on the function)
EMBED_WORKERS = 2    # parallel proxy calls (low, to stay under the rate limit)
ATTEMPTS = 6         # per-batch retries
CHECKPOINT = 60      # commit+push progress every N successful batches
OUTDIR = "ml/clip_v2"
SHARD = 1500
IMG = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{}.jpg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

_pace = threading.Lock()
_next = [0.0]        # shared earliest-allowed send time (simple global throttle)
MIN_GAP = 1.0        # seconds between proxy calls across all workers (~60/min)


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


def load_done():
    """Return {(game_id, shot): vector} already embedded in committed shards."""
    done = {}
    for p in sorted(glob.glob(f"{OUTDIR}/clip_*.json")):
        try:
            for it in json.load(open(p)).get("items", []):
                done[(it["game_id"], it["shot"])] = it["v"]
        except Exception:
            pass
    return done


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


def _throttle():
    with _pace:
        now = time.time()
        wait = _next[0] - now
        if wait > 0:
            time.sleep(wait)
        _next[0] = max(now, _next[0]) + MIN_GAP


def embed_batch(batch):
    # batch: list of (gid, shot, b64) -> list of (gid, shot, vector)
    for attempt in range(ATTEMPTS):
        _throttle()
        try:
            r = requests.post(PROXY, timeout=120,
                              json={"embed": [b[2] for b in batch], "token": TOKEN})
            if r.status_code == 200:
                embs = r.json().get("embeddings", [])
                if len(embs) == len(batch):
                    return [(batch[i][0], batch[i][1], embs[i]) for i in range(len(batch))]
                log(f"  bad payload: got {len(embs)} for {len(batch)}")
            else:
                log(f"  proxy {r.status_code} (attempt {attempt+1}): {r.text[:120]}")
        except Exception as e:
            log(f"  proxy error (attempt {attempt+1}): {e}")
        time.sleep(min(60, 4 * (2 ** attempt)))   # 4,8,16,32,60,60
    return []


def write_shards(merged):
    rows = [{"game_id": g, "shot": s, "v": v} for (g, s), v in
            sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][1]))]
    for old in glob.glob(f"{OUTDIR}/clip_*.json"):
        os.remove(old)
    for s in range(0, len(rows), SHARD):
        json.dump({"items": rows[s:s + SHARD]}, open(f"{OUTDIR}/clip_{s // SHARD:02d}.json", "w"))
    return len(rows)


def checkpoint(merged, final=False):
    n = write_shards(merged)
    try:
        subprocess.run(["git", "config", "user.name", "orarr2"], check=False)
        subprocess.run(["git", "config", "user.email", "orarbeli1@gmail.com"], check=False)
        subprocess.run(["git", "add", OUTDIR], check=False)
        msg = "Add jina-clip-v2 screenshot embeddings [skip ci]"
        c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if c.returncode == 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False,
                           capture_output=True, text=True)
            p = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
            log(f"  checkpoint pushed: {n} vecs ({'ok' if p.returncode == 0 else p.stderr[:120]})")
    except Exception as e:
        log(f"  checkpoint push failed: {e}")
    return n


def main() -> int:
    t0 = time.time()
    os.makedirs(OUTDIR, exist_ok=True)
    games = fetch_games()
    merged = load_done()
    log(f"{len(games)} games · {len(merged)} vectors already embedded (resuming)")

    jobs = []
    for g in games:
        for idx, sid in enumerate((g["screenshot_ids"] or [])[:SHOTS]):
            if (g["id"], idx) not in merged:
                jobs.append((g["id"], idx, sid))
    log(f"{len(jobs)} screenshots still to embed")
    if not jobs:
        log("Nothing to do — already complete.")
        return 0

    log("Downloading…")
    items = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for r in ex.map(download, jobs):
            if r:
                items.append(r)
    log(f"  downloaded {len(items)} ({time.time()-t0:.0f}s)")

    log(f"Embedding via proxy (workers={EMBED_WORKERS}, batch={BATCH})…")
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    done_b, ok_b, since_ckpt = 0, 0, 0
    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as ex:
        for res in ex.map(embed_batch, batches):
            done_b += 1
            if res:
                ok_b += 1; since_ckpt += 1
                for gid, shot, v in res:
                    merged[(gid, shot)] = [round(float(x), 4) for x in v]
            if since_ckpt >= CHECKPOINT:
                since_ckpt = 0
                log(f"  {done_b}/{len(batches)} batches · {ok_b} ok · "
                    f"{len(merged)} vecs · {time.time()-t0:.0f}s")
                checkpoint(merged)

    n = checkpoint(merged, final=True)
    log(f"Batch success: {ok_b}/{len(batches)}  ({100*ok_b/max(1,len(batches)):.0f}%)")
    log(f"Total v2 embeddings on disk: {n}  ({time.time()-t0:.0f}s)")
    if ok_b < 0.9 * len(batches):
        log("WARNING: many batches failed — re-dispatch to continue (resumable).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

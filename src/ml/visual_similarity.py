"""Compute visual-similarity recommendations from IGDB gameplay screenshots.

For every PS4/PS5 game we:
  1. download up to N of its in-game screenshots from the IGDB CDN,
  2. embed each screenshot with a pretrained MobileNetV3 CNN,
  3. average the screenshot embeddings into one per-game "visual fingerprint",
  4. find each game's nearest visual neighbours by cosine similarity.

The result is written to src/ml/visual_neighbors.json:
    { "model": ..., "dim": ..., "shots": N, "count": G,
      "neighbors": { "<game_id>": { "ids": [...], "scores": [...] } } }

Runs in CI (open network). Reads games via the public Supabase REST API.

Env:
  SUPABASE_URL, SUPABASE_KEY   (anon key; public reads only)
  SHOTS   screenshots per game        (default 3)
  TOPK    neighbours per game         (default 12)
  LIMIT   cap number of games, 0=all  (default 0, for quick test runs)
  OUT     output path                 (default src/ml/visual_neighbors.json)
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

import torch
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
SHOTS = int(os.environ.get("SHOTS", "3"))
TOPK = int(os.environ.get("TOPK", "12"))
LIMIT = int(os.environ.get("LIMIT", "0"))
OUT = os.environ.get("OUT", "src/ml/visual_neighbors.json")

IMG = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{}.jpg"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
CHUNK = 256  # games processed per batch (bounds memory)


def log(*a):
    print(*a, flush=True)


def fetch_games() -> list[dict]:
    """Page through public.games via PostgREST, newest API key auth."""
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    out, offset, page = [], 0, 1000
    while True:
        url = (f"{SUPABASE_URL}/rest/v1/games"
               f"?select=id,screenshot_ids&order=id.asc&limit={page}&offset={offset}")
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        rows = r.json()
        out.extend(rows)
        if len(rows) < page:
            break
        offset += page
    # keep only games that actually have screenshots
    out = [g for g in out if g.get("screenshot_ids")]
    if LIMIT:
        out = out[:LIMIT]
    return out


def load_model():
    weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    model = mobilenet_v3_small(weights=weights)
    model.classifier = torch.nn.Identity()  # keep the 576-d pooled features
    model.eval()
    pre = weights.transforms()  # resize/crop/normalise to match training
    return model, pre


def export_onnx(model, path="src/docs/models/mobilenet_v3_small.onnx"):
    """Export the same feature extractor for in-browser (onnxruntime-web) use,
    so a photo embedded in the browser is comparable to the stored game vectors.
    Input: normalised 1x3x224x224 (ImageNet)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dummy = torch.randn(1, 3, 224, 224)
    torch.onnx.export(
        model, dummy, path,
        input_names=["input"], output_names=["embedding"],
        dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=17,
        dynamo=False,  # legacy exporter → single self-contained .onnx (no .data)
    )
    log("Exported ONNX model →", path, f"({os.path.getsize(path)//1024} KB)")


def fetch_image(image_id: str):
    try:
        r = requests.get(IMG.format(image_id), headers={"User-Agent": UA}, timeout=20)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def main() -> int:
    t0 = time.time()
    log("Fetching game list…")
    games = fetch_games()
    log(f"  {len(games)} games with screenshots")

    model, pre = load_model()
    log("Model loaded (mobilenet_v3_small, 576-d).")
    export_onnx(model)

    ids: list[int] = []
    vecs: list[np.ndarray] = []

    for start in range(0, len(games), CHUNK):
        chunk = games[start:start + CHUNK]
        # (game_index_in_chunk, image_id) download jobs
        jobs = []
        for gi, g in enumerate(chunk):
            for sid in (g["screenshot_ids"] or [])[:SHOTS]:
                jobs.append((gi, sid))

        tensors_by_game: dict[int, list[torch.Tensor]] = {}
        with ThreadPoolExecutor(max_workers=32) as ex:
            results = ex.map(lambda j: (j[0], fetch_image(j[1])), jobs)
            for gi, im in results:
                if im is None:
                    continue
                tensors_by_game.setdefault(gi, []).append(pre(im))

        # embed everything in this chunk in one batch
        flat, owners = [], []
        for gi, ts in tensors_by_game.items():
            for t in ts:
                flat.append(t)
                owners.append(gi)
        if not flat:
            continue
        with torch.no_grad():
            feats = model(torch.stack(flat)).cpu().numpy()  # (M, 576)

        # mean-pool per game
        for gi in range(len(chunk)):
            rows = feats[[k for k, o in enumerate(owners) if o == gi]]
            if rows.shape[0] == 0:
                continue
            v = rows.mean(axis=0)
            n = np.linalg.norm(v)
            if n == 0:
                continue
            ids.append(int(chunk[gi]["id"]))
            vecs.append((v / n).astype(np.float32))

        log(f"  embedded {len(ids)}/{len(games)} games "
            f"({time.time() - t0:.0f}s)")

    if not vecs:
        log("ERROR: no embeddings produced")
        return 1

    E = np.vstack(vecs)                      # (G, 576), L2-normalised
    log(f"Computing neighbours for {E.shape[0]} games…")
    sims = E @ E.T                           # cosine similarity
    np.fill_diagonal(sims, -1.0)             # exclude self

    neighbors = {}
    k = min(TOPK, E.shape[0] - 1)
    for i, gid in enumerate(ids):
        idx = np.argpartition(-sims[i], k)[:k]
        idx = idx[np.argsort(-sims[i][idx])]
        neighbors[str(gid)] = {
            "ids": [ids[j] for j in idx],
            "scores": [round(float(sims[i][j]), 4) for j in idx],
        }

    payload = {
        "model": "mobilenet_v3_small/imagenet",
        "dim": int(E.shape[1]),
        "shots": SHOTS,
        "count": len(ids),
        "neighbors": neighbors,
    }
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f)
    log(f"Wrote {OUT} ({len(ids)} games) in {time.time() - t0:.0f}s")

    # per-game vectors for in-browser photo search (loaded into pgvector), sharded
    emb = [{"id": ids[i], "v": [round(float(x), 5) for x in vecs[i]]} for i in range(len(ids))]
    os.makedirs("src/ml/embeddings", exist_ok=True)
    SH = 1000
    for s in range(0, len(emb), SH):
        p = f"src/ml/embeddings/game_embeddings_{s // SH:02d}.json"
        json.dump({"items": emb[s:s + SH]}, open(p, "w"))
        log("wrote", p, len(emb[s:s + SH]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

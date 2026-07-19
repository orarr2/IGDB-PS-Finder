"""Photo-search self-retrieval evaluation.

For each game with >=4 screenshots, use a screenshot that is NOT in the
production index (shot #3 - production only ingests 0,1,2) as the query.
Embed it, call match_games_by_clip_oss, and measure whether the source game
comes back at rank 1 / 5 / 10.

This is ground truth without any labeling: it's the exact question a user
asks when they photograph a game they're playing.
"""
from __future__ import annotations

import json, random, time
from typing import Any

from common import fetch_image_bytes, rpc, rest_paged, save_results, bootstrap_ci
from embed_clip import embed_bytes

# Which screenshot index to use as the query. 0..2 are in game_clip_oss;
# 3+ have never been seen by the model = clean held-out set.
HELDOUT_SHOT_IDX = 3
SAMPLE_SIZE = 300
SEED = 20260719
TOP_K = 20  # ask for 20 candidates so Recall@10 is meaningful


def build_test_set(n: int, seed: int) -> list[dict]:
    """Games that have >=4 screenshots AND are in game_clip_oss (i.e. the
    catalog can theoretically return them)."""
    print(f"[{time.strftime('%H:%M:%S')}] fetching game catalog ...")
    games = rest_paged("games?select=id,name,screenshot_ids&order=id.asc")
    games = [g for g in games if len(g.get("screenshot_ids") or []) > HELDOUT_SHOT_IDX]
    print(f"  {len(games)} games have >= {HELDOUT_SHOT_IDX + 1} screenshots")

    covered_rows = rest_paged("game_clip_oss?select=game_id&order=game_id.asc")
    covered = {r["game_id"] for r in covered_rows}
    games = [g for g in games if g["id"] in covered]
    print(f"  {len(games)} of those are indexed in game_clip_oss")

    rng = random.Random(seed)
    rng.shuffle(games)
    return games[:n]


def run(sample_size: int = SAMPLE_SIZE, label: str = "baseline") -> dict:
    test = build_test_set(sample_size, SEED)
    print(f"[{time.strftime('%H:%M:%S')}] evaluating {len(test)} games ...")

    ranks: list[int | None] = []  # rank of the source game in results, or None
    latencies_ms: list[float] = []
    failed_download = 0
    failed_embed = 0
    empty_result = 0
    genre_hits: list[float] = []

    for i, g in enumerate(test, 1):
        image_id = g["screenshot_ids"][HELDOUT_SHOT_IDX]
        blob = fetch_image_bytes(image_id, "screenshot_med")
        if blob is None:
            failed_download += 1
            ranks.append(None)
            continue
        vec = embed_bytes(blob)
        if vec is None:
            failed_embed += 1
            ranks.append(None)
            continue

        t0 = time.perf_counter()
        try:
            results = rpc("match_games_by_clip_oss", {"query": json.dumps(vec.tolist()), "lim": TOP_K})
        except Exception as e:
            print(f"  [{i}/{len(test)}] {g['name']!r}: RPC error {e}")
            ranks.append(None)
            continue
        latencies_ms.append((time.perf_counter() - t0) * 1000)

        if not results:
            empty_result += 1
            ranks.append(None)
            continue

        # Where did the source game come back?
        rank = next((idx + 1 for idx, r in enumerate(results) if r["id"] == g["id"]), None)
        ranks.append(rank)

        # Genre coherence: what fraction of the top 5 share a genre with source?
        src_genres = set(g.get("genres") or [])
        # We need genres of results - fetch from returned rows
        src_rows = rest_paged(f"games?id=eq.{g['id']}&select=genres")
        if src_rows:
            src_genres = set(src_rows[0].get("genres") or [])
        if src_genres:
            top5 = results[:5]
            shared = sum(1 for r in top5 if src_genres & set(r.get("genres") or []))
            genre_hits.append(shared / len(top5))

        if i % 25 == 0:
            recall1 = sum(1 for r in ranks if r == 1) / len(ranks)
            print(f"  [{i}/{len(test)}] running R@1={recall1:.3f}")

    # Metrics
    n = len(ranks)
    def recall_at(k: int) -> list[int]:
        return [1 if (r is not None and r <= k) else 0 for r in ranks]
    r1 = recall_at(1)
    r5 = recall_at(5)
    r10 = recall_at(10)
    r20 = recall_at(20)
    mrr = [1.0 / r if r else 0.0 for r in ranks]

    def mean_and_ci(vals: list[float]) -> dict:
        m = sum(vals) / len(vals) if vals else 0.0
        lo, hi = bootstrap_ci(vals)
        return {"mean": round(m, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)}

    latencies_ms.sort()
    p = lambda q: latencies_ms[int(len(latencies_ms) * q)] if latencies_ms else 0

    out = {
        "meta": {
            "label": label,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sample_size": sample_size,
            "actual_evaluated": n,
            "held_out_shot": HELDOUT_SHOT_IDX,
            "top_k": TOP_K,
            "seed": SEED,
        },
        "recall": {
            "at_1": mean_and_ci(r1),
            "at_5": mean_and_ci(r5),
            "at_10": mean_and_ci(r10),
            "at_20": mean_and_ci(r20),
        },
        "mrr": mean_and_ci(mrr),
        "genre_coherence_top5": mean_and_ci(genre_hits),
        "failures": {
            "download": failed_download,
            "embed": failed_embed,
            "empty_result": empty_result,
        },
        "latency_ms": {
            "p50": round(p(0.50), 1),
            "p95": round(p(0.95), 1),
            "p99": round(p(0.99), 1),
        },
    }
    return out


if __name__ == "__main__":
    import sys
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    size = int(sys.argv[2]) if len(sys.argv) > 2 else SAMPLE_SIZE
    result = run(sample_size=size, label=label)
    p = save_results(f"photo_search_{label}", result)
    print(f"\nSaved: {p}\n")
    print(json.dumps(result, indent=2))

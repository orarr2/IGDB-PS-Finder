"""Recommendation ranking evaluation using metadata-derived ground truth.

Relevance model (per source game):
  3 = same collection (God of War II is very relevant to God of War)
  2 = same developer AND overlapping genre (>=1)
  1 = in the source's similar_games AND in-catalog
  0 = otherwise

Metrics computed per source, then averaged with bootstrap CI:
  - nDCG@12   (dominant metric - captures order too, not just presence)
  - Recall@12 (fraction of relevant items surfaced)
  - MRR        (position of first relevant hit)

Works on any recommendation RPC (get_recommendations, get_visual_recommendations, get_hidden_gems).
"""
from __future__ import annotations

import json, math, random, time
from typing import Any

from common import rest_paged, rpc, save_results, bootstrap_ci

SAMPLE_SIZE = 300
SEED = 20260719
TOP_K = 12


def build_source_pool(n: int, seed: int) -> list[dict]:
    """Games with at least one collection (so relevance labels have signal).
    Ordered by rating desc so we test on titles users actually pick."""
    print(f"[{time.strftime('%H:%M:%S')}] fetching source pool ...")
    rows = rest_paged(
        "games?select=id,name,collections,developers,genres,similar_games,total_rating,total_rating_count"
        "&order=total_rating_count.desc.nullslast&collections=not.eq.{}"
    )
    # Client-side filter (belt & braces).
    rows = [r for r in rows if (r.get("collections") or []) and (r.get("total_rating_count") or 0) >= 20]
    print(f"  {len(rows)} candidate source games with a collection and >=20 reviews")
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:n]


def relevance_labels(source: dict, all_games_index: dict[int, dict]) -> dict[int, int]:
    """Map game_id -> relevance grade for this source. Only in-catalog games."""
    src_collections = set(source.get("collections") or [])
    src_devs = set(source.get("developers") or [])
    src_genres = set(source.get("genres") or [])
    src_similar = set(source.get("similar_games") or [])
    src_id = source["id"]

    labels: dict[int, int] = {}
    # Grade 1: similar_games hits (in-catalog only)
    for sid in src_similar:
        if sid in all_games_index and sid != src_id:
            labels[sid] = max(labels.get(sid, 0), 1)
    # Grade 2: same-dev + genre overlap
    if src_devs and src_genres:
        for g in all_games_index.values():
            if g["id"] == src_id:
                continue
            gdevs = set(g.get("developers") or [])
            ggenres = set(g.get("genres") or [])
            if src_devs & gdevs and src_genres & ggenres:
                labels[g["id"]] = max(labels.get(g["id"], 0), 2)
    # Grade 3: same collection
    if src_collections:
        for g in all_games_index.values():
            if g["id"] == src_id:
                continue
            if src_collections & set(g.get("collections") or []):
                labels[g["id"]] = 3
    return labels


def dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def ndcg_at_k(pred_ids: list[int], labels: dict[int, int], k: int) -> float:
    pred_rels = [labels.get(pid, 0) for pid in pred_ids[:k]]
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = dcg(ideal)
    return dcg(pred_rels) / idcg if idcg > 0 else 0.0


def recall_at_k(pred_ids: list[int], labels: dict[int, int], k: int) -> float:
    relevant = {gid for gid, r in labels.items() if r > 0}
    if not relevant:
        return 0.0
    hits = sum(1 for pid in pred_ids[:k] if pid in relevant)
    return hits / min(len(relevant), k)


def mrr_of(pred_ids: list[int], labels: dict[int, int]) -> float:
    relevant = {gid for gid, r in labels.items() if r > 0}
    for i, pid in enumerate(pred_ids, 1):
        if pid in relevant:
            return 1.0 / i
    return 0.0


def run(rpc_name: str = "get_recommendations", sample_size: int = SAMPLE_SIZE, label: str = "baseline") -> dict:
    print(f"[{time.strftime('%H:%M:%S')}] loading full catalog for GT ...")
    all_games = rest_paged(
        "games?select=id,name,collections,developers,genres,similar_games"
    )
    idx = {g["id"]: g for g in all_games}
    print(f"  {len(idx)} games indexed")

    sources = build_source_pool(sample_size, SEED)

    ndcgs, recalls, mrrs, latencies = [], [], [], []
    skipped_no_gt = 0

    for i, src in enumerate(sources, 1):
        labels = relevance_labels(src, idx)
        if not any(r > 0 for r in labels.values()):
            skipped_no_gt += 1
            continue

        t0 = time.perf_counter()
        try:
            recs = rpc(rpc_name, {"source_id": src["id"], "lim": TOP_K})
        except Exception as e:
            print(f"  [{i}] {src['name']!r}: RPC error {e}")
            continue
        latencies.append((time.perf_counter() - t0) * 1000)

        pred_ids = [r["id"] for r in recs]
        ndcgs.append(ndcg_at_k(pred_ids, labels, TOP_K))
        recalls.append(recall_at_k(pred_ids, labels, TOP_K))
        mrrs.append(mrr_of(pred_ids, labels))

        if i % 25 == 0:
            m = sum(ndcgs) / len(ndcgs)
            print(f"  [{i}/{len(sources)}] running nDCG@{TOP_K}={m:.3f}")

    def mean_and_ci(vals: list[float]) -> dict:
        m = sum(vals) / len(vals) if vals else 0.0
        lo, hi = bootstrap_ci(vals)
        return {"mean": round(m, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)}

    latencies.sort()
    p = lambda q: latencies[int(len(latencies) * q)] if latencies else 0.0

    return {
        "meta": {
            "label": label,
            "rpc": rpc_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sample_size": sample_size,
            "actual_evaluated": len(ndcgs),
            "skipped_no_ground_truth": skipped_no_gt,
            "top_k": TOP_K,
            "seed": SEED,
        },
        "ndcg_at_12": mean_and_ci(ndcgs),
        "recall_at_12": mean_and_ci(recalls),
        "mrr": mean_and_ci(mrrs),
        "latency_ms": {"p50": round(p(0.50), 1), "p95": round(p(0.95), 1)},
    }


if __name__ == "__main__":
    import sys
    rpc_name = sys.argv[1] if len(sys.argv) > 1 else "get_recommendations"
    label = sys.argv[2] if len(sys.argv) > 2 else "baseline"
    size = int(sys.argv[3]) if len(sys.argv) > 3 else SAMPLE_SIZE
    result = run(rpc_name=rpc_name, sample_size=size, label=label)
    p = save_results(f"recs_{rpc_name}_{label}", result)
    print(f"\nSaved: {p}\n")
    print(json.dumps(result, indent=2))

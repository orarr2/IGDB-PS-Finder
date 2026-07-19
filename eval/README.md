# Evaluation harness

Objective, reproducible measurement of the recommendation and photo-search
engines. Every change to the ranking logic must be preceded and followed by a
run so the impact is measured, not guessed.

All calls are **read-only** with the anon key (from `src/docs/config.js`); no
service key needed. Results land under `eval/results/`.

## Metrics

### Photo search (`photo_search.py`)

Self-retrieval: the production index contains screenshots 0-2 for every
game. Screenshot #3 has never been seen by the model, so it acts as a clean
held-out query. For each sampled game we embed its held-out shot and ask
`match_games_by_clip_oss` for the top 20 - the source game's rank tells us
whether the engine identifies what the user just photographed.

- **Recall@1 / @5 / @10 / @20** with bootstrap 95% CI
- **MRR** (mean reciprocal rank)
- **Genre coherence @5** - top-5 sharing a genre with the source
- **Latency p50 / p95 / p99** as anon over the public REST endpoint

### Recommendations (`recommendations.py`)

Metadata-derived ground truth per source game:

| Relevance | Definition |
|---|---|
| 3 | Same IGDB `collection` (sequel / same universe) |
| 2 | Same developer AND overlapping genre |
| 1 | In the source's `similar_games` (in-catalog only) |
| 0 | Otherwise |

- **nDCG@12** - primary; rewards putting the most-relevant items first
- **Recall@12** - fraction of relevant items surfaced
- **MRR** - position of the first relevant hit

Runs against `get_recommendations`, `get_visual_recommendations`, or
`get_hidden_gems` (pass the RPC name as CLI arg 1).

## Running

```bash
cd eval
python photo_search.py baseline           # default 300 games
python recommendations.py get_recommendations baseline
python recommendations.py get_visual_recommendations baseline
python recommendations.py get_hidden_gems baseline
```

First run downloads and embeds ~300 IGDB screenshots (~3-4 minutes on a
laptop CPU). Subsequent runs reuse `eval/cache/`.

## Reading the results

Each run writes `eval/results/<name>_YYYY-MM-DD_HHMMSS.json` with mean,
95% bootstrap CI, and full metadata (sample size, seed, RPC targeted,
timestamp). To claim a change actually improved things, the after-run's
mean should sit **outside** the before-run's CI band.

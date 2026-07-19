"""Compare two eval result files (baseline vs after) and print deltas.

Usage:
    python compare.py results/recs_get_recommendations_baseline_*.json \
                      results/recs_get_recommendations_after_*.json

Highlights metrics where the mean of one file falls OUTSIDE the 95% CI of
the other - the standard "is this improvement statistically meaningful"
check without pretending to run a full paired test (which would require
per-sample values, not summaries).
"""
from __future__ import annotations

import json, sys
from pathlib import Path


def load(p: str) -> dict:
    return json.loads(Path(p).read_text())


def walk(prefix: str, obj: dict, out: dict) -> None:
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and "mean" in v and "ci_lo" in v:
            out[key] = v
        elif isinstance(v, dict):
            walk(key, v, out)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare.py <before.json> <after.json>", file=sys.stderr)
        return 2
    before, after = load(sys.argv[1]), load(sys.argv[2])
    bm, am = {}, {}
    walk("", before, bm)
    walk("", after, am)

    keys = sorted(set(bm.keys()) & set(am.keys()))
    if not keys:
        print("No comparable metrics found.")
        return 1

    print(f"BEFORE: {before.get('meta', {}).get('label')} ({before.get('meta', {}).get('timestamp')})")
    print(f"AFTER:  {after.get('meta', {}).get('label')}  ({after.get('meta', {}).get('timestamp')})")
    print()
    print(f"{'metric':<30} {'before':>10}  {'after':>10}  {'delta':>10}  significance")
    print("-" * 82)
    for k in keys:
        b, a = bm[k], am[k]
        bmean, amean = b["mean"], a["mean"]
        delta = amean - bmean
        # A improved over B if A's mean is outside B's CI band.
        sig = "not sig"
        if amean > b["ci_hi"]:
            sig = "IMPROVED"
        elif amean < b["ci_lo"]:
            sig = "REGRESSED"
        print(f"{k:<30} {bmean:>10.4f}  {amean:>10.4f}  {delta:>+10.4f}  {sig}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

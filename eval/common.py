"""Shared helpers: config, REST calls, image cache. Read-only, anon key."""
from __future__ import annotations

import io, json, os, re, time
from pathlib import Path
from typing import Any

import requests

CFG_JS = Path(__file__).resolve().parents[1] / "src" / "docs" / "config.js"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> tuple[str, str]:
    txt = CFG_JS.read_text()
    url = re.search(r'SUPABASE_URL:\s*"([^"]+)"', txt).group(1)
    key = re.search(r'SUPABASE_KEY:\s*"([^"]+)"', txt).group(1)
    return url, key


URL, KEY = load_config()
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def rest_paged(query: str, page_size: int = 1000) -> list[dict]:
    """Follow PostgREST pagination (server caps at 200 rows regardless of limit)."""
    out, off = [], 0
    while True:
        u = f"{URL}/rest/v1/{query}&limit={page_size}&offset={off}"
        rows = requests.get(u, headers=HDR, timeout=60).json()
        if not isinstance(rows, list):
            raise RuntimeError(f"REST error: {rows}")
        if not rows:
            return out
        out.extend(rows)
        off += len(rows)


def rpc(fn: str, body: dict) -> list[dict]:
    r = requests.post(
        f"{URL}/rest/v1/rpc/{fn}",
        headers={**HDR, "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


IGDB_IMG = "https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"


def fetch_image_bytes(image_id: str, size: str = "screenshot_med") -> bytes | None:
    """Cached IGDB image fetch. Returns None on failure."""
    key = f"{size}_{image_id}.jpg"
    p = CACHE_DIR / key
    if p.exists():
        return p.read_bytes()
    try:
        r = requests.get(
            IGDB_IMG.format(size=size, image_id=image_id),
            headers={"User-Agent": "PS-Finder-eval/1.0"},
            timeout=20,
        )
        if r.status_code != 200:
            return None
        p.write_bytes(r.content)
        return r.content
    except Exception:
        return None


def save_results(name: str, obj: dict) -> Path:
    """Timestamped JSON dump under eval/results/."""
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    p = Path(__file__).resolve().parent / "results" / f"{name}_{stamp}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True))
    return p


def bootstrap_ci(values: list[float], n_boot: int = 2000, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean. Uses a fixed seed for reproducibility."""
    import random
    if not values:
        return (0.0, 0.0)
    rng = random.Random(42)
    n = len(values)
    boots = []
    for _ in range(n_boot):
        s = sum(values[rng.randrange(n)] for _ in range(n)) / n
        boots.append(s)
    boots.sort()
    lo = boots[int(n_boot * alpha / 2)]
    hi = boots[int(n_boot * (1 - alpha / 2))]
    return (lo, hi)

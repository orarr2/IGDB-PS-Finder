"""Collect *player-captured* in-game images (links only) from Steam & Reddit.

For each game we:
  - resolve a Steam appid (Steam storefront search) and scrape a few top
    community screenshots (genuine player uploads), and
  - search Reddit for image posts mentioning the game,
storing only the image URL + attribution (author, permalink) — never the file
itself. Output -> ml/user_media.json, later loaded into public.user_media.

This is a personal/research-scale collector: it rate-limits politely, keeps a
small number of items per game, and records source links for attribution.

Env:
  SUPABASE_URL, SUPABASE_KEY     (anon; read game list)
  MODE        'pilot' | 'all'    (default pilot)
  PILOT_N     games in pilot     (default 30, most-reviewed first)
  PER_GAME    images per source  (default 4)
  OUT         output path        (default ml/user_media.json)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
MODE = os.environ.get("MODE", "pilot")
PILOT_N = int(os.environ.get("PILOT_N", "30"))
PER_GAME = int(os.environ.get("PER_GAME", "4"))
OUT = os.environ.get("OUT", "ml/user_media.json")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA})

STEAM_IMG = re.compile(r'https://steamuserimages-a\.akamaihd\.net/ugc/[0-9A-Za-z/_\-]+(?:/[0-9A-Za-z/_\-]+)?')
STEAM_FILE = re.compile(r'https://steamcommunity\.com/sharedfiles/filedetails/\?id=\d+')


def log(*a):
    print(*a, flush=True)


def fetch_games():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    sel = "select=id,name,total_rating_count&order=total_rating_count.desc.nullslast"
    if MODE == "pilot":
        url = f"{SUPABASE_URL}/rest/v1/games?{sel}&limit={PILOT_N}"
        return S.get(url, headers=headers, timeout=60).json()
    out, off = [], 0
    while True:
        url = f"{SUPABASE_URL}/rest/v1/games?{sel}&limit=1000&offset={off}"
        rows = S.get(url, headers=headers, timeout=60).json()
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def steam_appid(name: str):
    try:
        r = S.get("https://store.steampowered.com/api/storesearch/",
                  params={"term": name, "cc": "us", "l": "en"}, timeout=20)
        items = r.json().get("items", [])
        target = norm(name)
        for it in items:                       # prefer an exact-ish title match
            if norm(it.get("name", "")) == target:
                return it["id"]
        return items[0]["id"] if items else None
    except Exception:
        return None


def steam_screenshots(appid: int, n: int):
    try:
        url = (f"https://steamcommunity.com/app/{appid}/screenshots/"
               f"?p=1&browsefilter=toprated&l=english")
        html = S.get(url, timeout=25).text
    except Exception:
        return []
    imgs = STEAM_IMG.findall(html)
    files = STEAM_FILE.findall(html)
    out, seen = [], set()
    for i, img in enumerate(imgs):
        if img in seen:
            continue
        seen.add(img)
        out.append({
            "source": "steam",
            "image_url": img,
            "thumb_url": img,
            "author": "Steam player",
            "source_url": files[i] if i < len(files) else url,
            "caption": None,
        })
        if len(out) >= n:
            break
    return out


def reddit_images(name: str, n: int):
    try:
        r = S.get("https://www.reddit.com/search.json",
                  params={"q": f'"{name}"', "sort": "top", "t": "all",
                          "limit": 30, "type": "link"}, timeout=25)
        children = r.json().get("data", {}).get("children", [])
    except Exception:
        return []
    token = norm(name)
    out = []
    for c in children:
        d = c.get("data", {})
        url = d.get("url_overridden_by_dest") or d.get("url", "")
        is_img = (d.get("post_hint") == "image"
                  or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                  or "i.redd.it" in url)
        if not is_img:
            continue
        if token not in norm(d.get("title", "")):   # cut obvious off-topic noise
            continue
        thumb = d.get("thumbnail")
        out.append({
            "source": "reddit",
            "image_url": url,
            "thumb_url": thumb if isinstance(thumb, str) and thumb.startswith("http") else None,
            "author": "u/" + d.get("author", "?"),
            "source_url": "https://www.reddit.com" + d.get("permalink", ""),
            "caption": d.get("title"),
        })
        if len(out) >= n:
            break
    return out


def main() -> int:
    games = fetch_games()
    log(f"{MODE}: {len(games)} games")
    items, stats = [], {"steam": 0, "reddit": 0, "with_any": 0}

    for gi, g in enumerate(games, 1):
        gid, name = g["id"], g["name"]
        rows = []

        appid = steam_appid(name)
        time.sleep(0.4)
        if appid:
            rows += steam_screenshots(appid, PER_GAME)
            time.sleep(0.6)

        rows += reddit_images(name, PER_GAME)
        time.sleep(1.2)  # be polite to reddit

        for r in rows:
            r["game_id"] = gid
            items.append(r)
        s = sum(1 for r in rows if r["source"] == "steam")
        rd = sum(1 for r in rows if r["source"] == "reddit")
        stats["steam"] += s
        stats["reddit"] += rd
        if rows:
            stats["with_any"] += 1
        log(f"  [{gi}/{len(games)}] {name[:38]:38} steam={s} reddit={rd}")

    payload = {"mode": MODE, "per_game": PER_GAME, "items": items, "stats": stats}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f)
    log(f"Wrote {OUT}: {len(items)} links "
        f"(steam={stats['steam']}, reddit={stats['reddit']}, "
        f"{stats['with_any']}/{len(games)} games covered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

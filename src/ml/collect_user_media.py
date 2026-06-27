"""Collect *player-captured* in-game screenshots (links only) from Steam.

For each game we resolve a Steam appid (storefront search), pull the top
community screenshots via Steam's screenshot AJAX endpoint, and read each
screenshot's full-resolution image URL from its details page. We store only the
image URL + source link (attribution) - never the file itself.

Output -> ml/user_media.json, later loaded into public.user_media.

Game list source (in priority order):
  - GAMES_FILE env (a JSON array of {id,name}); default ml/pilot_games.json
  - else Supabase REST (needs SUPABASE_URL / SUPABASE_KEY), most-reviewed first

Env:
  GAMES_FILE   path to a JSON [{id,name}]   (default ml/pilot_games.json)
  PER_GAME     screenshots per game         (default 4)
  MODE/PILOT_N used only for the Supabase path
  OUT          output path                  (default ml/user_media.json)
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time

import requests

PER_GAME = int(os.environ.get("PER_GAME", "4"))
OUT = os.environ.get("OUT", "ml/user_media.json")
GAMES_FILE = os.environ.get("GAMES_FILE", "ml/pilot_games.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

FILEDETAILS = re.compile(r'https://steamcommunity\.com/sharedfiles/filedetails/\?id=\d+')
# player screenshot image URLs (newer CDN); the base path (without the ?imw/imh
# sizing query) is the full-resolution original.
UGC_IMG = re.compile(r'https://images\.steamusercontent\.com/ugc/[0-9A-Za-z/_\-]+')


def get(url, tries=3):
    """GET with light retry/backoff (Steam throttles bursts of requests)."""
    for i in range(tries):
        try:
            r = S.get(url, timeout=25)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 403, 503):
                time.sleep(4 * (i + 1) + random.random())
                continue
            return r.text
        except Exception:
            time.sleep(2 * (i + 1))
    return ""


def log(*a):
    print(*a, flush=True)


def load_games():
    if GAMES_FILE and os.path.exists(GAMES_FILE):
        return json.load(open(GAMES_FILE))
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        log("No GAMES_FILE and no Supabase creds - nothing to do.")
        return []
    n = int(os.environ.get("PILOT_N", "30"))
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    sel = "select=id,name&order=total_rating_count.desc.nullslast&limit=" + str(n)
    return S.get(f"{url}/rest/v1/games?{sel}", headers=headers, timeout=60).json()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def steam_appid(name: str):
    try:
        r = S.get("https://store.steampowered.com/api/storesearch/",
                  params={"term": name, "cc": "us", "l": "en"}, timeout=20)
        items = r.json().get("items", [])
    except Exception as e:
        log("   storesearch error:", e)
        return None
    if not items:
        return None
    target = norm(name)
    for it in items:
        if norm(it.get("name", "")) == target:
            return it["id"], it["name"]
    # fall back to the first hit only if it shares the leading word
    first = items[0]
    if norm(first.get("name", "")).startswith(target[:6]) or target.startswith(norm(first.get("name", ""))[:6]):
        return first["id"], first.get("name")
    return None


def steam_screenshots(appid: int, n: int):
    """Top community screenshots via one homecontent request - image URLs and
    their source links are parsed straight from the listing (no per-screenshot
    page visits, so far fewer requests = far less throttling)."""
    url = (f"https://steamcommunity.com/app/{appid}/homecontent/"
           f"?userreviewsoffset=0&p=1&screenshotspage=1&numperpage=12"
           f"&browsefilter=toprated&appHubSubSection=2&l=english"
           f"&appid={appid}&forceanon=1")
    html = get(url)
    files = FILEDETAILS.findall(html)
    imgs, seen = [], set()
    for m in UGC_IMG.findall(html):
        base = m  # already excludes the ?imw/imh query → full-res original
        if base not in seen:
            seen.add(base)
            imgs.append(base)
    out = []
    for i, img in enumerate(imgs[:n]):
        out.append({
            "source": "steam",
            "image_url": img,
            "thumb_url": img,
            "author": "Steam player",
            "source_url": files[i] if i < len(files) else url,
            "caption": None,
        })
    return out


def main() -> int:
    games = load_games()
    log(f"{len(games)} games (source: {GAMES_FILE if os.path.exists(GAMES_FILE) else 'supabase'})")
    items, covered = [], 0

    for gi, g in enumerate(games, 1):
        gid, name = g["id"], g["name"]
        hit = steam_appid(name)
        time.sleep(0.5)
        rows = []
        if hit:
            appid, sname = hit
            rows = steam_screenshots(appid, PER_GAME)
            for r in rows:
                r["game_id"] = gid
            items.extend(rows)
        if rows:
            covered += 1
        log(f"  [{gi}/{len(games)}] {name[:34]:34} "
            f"appid={hit[0] if hit else '-':>8}  shots={len(rows)}")
        time.sleep(1.6 + random.random() * 1.6)  # gentle on Steam's rate limits

    payload = {"source": "steam", "per_game": PER_GAME, "items": items,
               "covered": covered, "games": len(games)}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump(payload, open(OUT, "w"))
    log(f"Wrote {OUT}: {len(items)} screenshots across "
        f"{covered}/{len(games)} games")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Collect *player-captured* in-game screenshots (links only) from Steam.

For each game we resolve a Steam appid (storefront search), pull the top
community screenshots via Steam's screenshot AJAX endpoint, and read each
screenshot's full-resolution image URL from its details page. We store only the
image URL + source link (attribution) — never the file itself.

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
# full-resolution screenshot URLs live on the details page's og:image
OG_IMAGE = re.compile(r'<meta property="og:image"\s+content="([^"]+)"')
# the user/profile that posted it
AUTHOR = re.compile(r'<div class="creatorsBlock">.*?<div class="friendBlockContent">\s*([^<\r\n]+)',
                    re.S)


def log(*a):
    print(*a, flush=True)


def load_games():
    if GAMES_FILE and os.path.exists(GAMES_FILE):
        return json.load(open(GAMES_FILE))
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        log("No GAMES_FILE and no Supabase creds — nothing to do.")
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


def screenshot_ids(appid: int):
    """Top community screenshots via the homecontent AJAX endpoint."""
    url = (f"https://steamcommunity.com/app/{appid}/homecontent/"
           f"?userreviewsoffset=0&p=1&screenshotspage=1&numperpage=12"
           f"&browsefilter=toprated&appHubSubSection=2&l=english"
           f"&appid={appid}&forceanon=1")
    try:
        html = S.get(url, timeout=25).text
    except Exception as e:
        log("   homecontent error:", e)
        return []
    seen, out = set(), []
    for m in FILEDETAILS.findall(html):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def full_image(filedetails_url: str):
    try:
        html = S.get(filedetails_url + "&l=english", timeout=20).text
    except Exception:
        return None, None
    img = OG_IMAGE.search(html)
    if not img:
        return None, None
    url = img.group(1).split("?")[0]  # strip sizing query for full res
    auth = AUTHOR.search(html)
    return url, (auth.group(1).strip() if auth else "Steam player")


def steam_screenshots(appid: int, n: int):
    ids = screenshot_ids(appid)
    out = []
    for fd in ids:
        if len(out) >= n:
            break
        img, author = full_image(fd)
        time.sleep(0.3)
        if not img:
            continue
        out.append({
            "source": "steam",
            "image_url": img,
            "thumb_url": img,
            "author": author,
            "source_url": fd,
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
        time.sleep(0.4)

    payload = {"source": "steam", "per_game": PER_GAME, "items": items,
               "covered": covered, "games": len(games)}
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    json.dump(payload, open(OUT, "w"))
    log(f"Wrote {OUT}: {len(items)} screenshots across "
        f"{covered}/{len(games)} games")
    return 0


if __name__ == "__main__":
    sys.exit(main())

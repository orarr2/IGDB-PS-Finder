# PlayStation Game Recommender — iPhone app

This folder is a complete, installable **iPhone app** (a Progressive Web App).
It opens in Safari, installs to your Home Screen with its own icon, runs
full-screen with no browser chrome, and works offline for the shell.

It gives **real results**: it calls the same live Supabase backend the desktop
app uses — the 3,840 PS4/PS5 games collected by `igdb_data_collection.ipynb` —
through the `search_games` and `get_recommendations` database functions. Cover
art is streamed from the IGDB CDN.

```
Search a game you love  →  See its details  →  Get 9 real recommendations  →  Share
```

No App Store, no Mac, no Xcode required.

---

## Run it on your iPhone

### Option A — GitHub Pages (recommended, nothing to keep running)

This app lives in the `docs/` folder so GitHub Pages can serve it with the
simple **"Deploy from a branch"** method — no Actions workflow needed.

1. Make the repo **public** (Pages on a private repo needs a paid plan).
2. In the repo: **Settings → Pages → Build and deployment**:
   - **Source:** _Deploy from a branch_
   - **Branch:** the branch this app is on → **Folder: `/docs`** → **Save**.
3. Wait ~1 minute. Pages shows a URL like
   `https://<your-username>.github.io/<repo>/`.
4. On your **iPhone**, open that URL in **Safari**.
5. Tap the **Share** button → **Add to Home Screen** → **Add**.
6. Launch it from the new Home-Screen icon. It now runs like a native app.

> HTTPS (which Pages provides) is required for Home-Screen install. Use Safari —
> Chrome/Firefox on iOS can open the app but can't install it to the Home Screen.
> The `.nojekyll` file in this folder tells Pages to serve the files as-is.

### Option B — From your computer over Wi-Fi (quick test)

Your iPhone and computer must be on the same Wi-Fi network.

```bash
cd docs
python3 -m http.server 8000
```

Find your computer's local IP (`ipconfig getifaddr en0` on macOS,
`hostname -I` on Linux), then on the iPhone open
`http://<that-ip>:8000`. (Add to Home Screen still works; full PWA install needs
the HTTPS Pages URL from Option A.)

---

## How to use it / what to "ask" it

- Type a game you love (e.g. **God of War**, **Elden Ring**, **The Last of
  Us**) and tap **Search**.
- Pick the match to see its rating, studio, genres/themes and summary.
- Tap **See 9 recommendations** — it asks the recommendation engine which
  PS4/PS5 games are most similar and shows them with cover art and ratings.
- Tap any recommendation to dive into it and recommend from there.
- Tap **Share** to send the list via the iOS share sheet.

## What's in here

| File | Purpose |
|---|---|
| `index.html` | App shell / three screens |
| `styles.css` | Mobile-first PlayStation theme, iPhone safe-area aware |
| `app.js` | Search / detail / recommendations logic, calls Supabase REST |
| `config.js` | Public Supabase URL + publishable (anon) key |
| `manifest.webmanifest` | Makes it an installable app (name, icons, colors) |
| `sw.js` | Service worker — installability + offline shell + cover cache |
| `icons/` | Home-screen app icons |
| `test/` | Headless verification of the full flow (`npm test`) |

## The key is safe to ship

`config.js` holds the Supabase **publishable / anon** key. It's designed to live
in clients: Row-Level Security on the `games` table allows anonymous **reads
only**, so the key cannot change or delete any data.

## Verify it yourself

```bash
cd ios-app/test
npm install
npm test
```

This loads the real page, feeds it the exact payloads the live database returned
for a "God of War" search, and asserts the search → detail → recommendations
flow renders that data correctly.

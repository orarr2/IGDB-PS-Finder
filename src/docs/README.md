# PS Finder - the web / iPhone / Android app

> This file covers **running and installing the app**. Setup from scratch,
> architecture, how the engines score, and troubleshooting live in the
> [top-level README](../../README.md) - that's the source of truth.

This folder is the live app - a complete, installable **Progressive Web App**.
It installs to your Home Screen with its own icon, runs full-screen with no
browser chrome, and works offline for the shell.

It gives **real results**: it calls the same live Supabase backend the desktop
app uses - **7,000+ PS1-PS5 games** collected by
`src/desktop_app/collect_igdb.py` - through the `search_games`,
`get_recommendations`, `get_visual_recommendations`, `get_hidden_gems` and
`match_games_by_clip_oss` database functions. Cover art and screenshots are
streamed from the IGDB CDN.

### What it does

- **Type-ahead search** - suggestions appear as you type ("God of…" → all the
  God of War games, etc.).
- **Search by a photo** - upload any screenshot or photo; a CLIP model runs
  **on your device** (transformers.js - the image never leaves the phone) and
  the backend matches its embedding against ~19,000 gameplay-screenshot
  vectors. The closest-looking games come back as results.
- **Detail screen** - cover, rating, studio, genres/themes, summary, a
  **screenshot gallery** (tap any shot for a full-quality, swipeable lightbox)
  and player-captured shots where available.
- **Three recommendation tabs**, 12 games each:
  - **Smart** - metadata engine: same series and studio lead, then genres,
    themes, quality and popularity.
  - **Looks alike** - computer vision on real gameplay screenshots.
  - **Hidden gems** - looks and feels like your pick, but with fewer than 25
    reviews.
  Press & hold a card to peek at its in-game screenshots; tap to open it.
- **"Why we picked this for you"** - on a recommended game, an explanation
  panel shows a match % and the exact reasons (same series / studio / genres /
  themes / IGDB-similar).
- **Upcoming** - the most-anticipated titles plus everything releasing in the
  next three months.
- **My List** - save games for later.
- **Share** the list via the native share sheet.

```
Type a game you love (or upload a photo) → details + screenshots
      → Smart / Looks alike / Hidden gems (12 each, with "why") → share
```

No App Store, no Mac, no Xcode required.

---

## Run it on your iPhone

### Option A - GitHub Pages (recommended, nothing to keep running)

This is how the live site is served today.

1. Make the repo **public** (Pages on a private repo needs a paid plan).
2. In the repo: **Settings → Pages → Build and deployment**:
   - **Source:** _Deploy from a branch_
   - **Branch:** `main` → **Folder: `/` (root)** → **Save**.
3. The repo's root `index.html` redirects the canonical URL into this folder
   (`src/docs/`), and the root `.nojekyll` tells Pages to serve the files
   as-is. Wait ~1 minute; Pages shows a URL like
   `https://<your-username>.github.io/<repo>/`.
4. On your **iPhone**, open that URL in **Safari**.
5. Tap the **Share** button → **Add to Home Screen** → **Add**.
6. Launch it from the new Home-Screen icon. It now runs like a native app.

> HTTPS (which Pages provides) is required for Home-Screen install. Use Safari -
> Chrome/Firefox on iOS can open the app but can't install it to the Home
> Screen.
>
> There is also a `deploy-pages.yml` workflow that can publish this folder via
> GitHub Actions instead - but it serves `src/docs/` as the site **root**,
> which changes every URL. The branch method above is the one this repo uses.

### Option B - From your computer over Wi-Fi (quick test)

Your iPhone and computer must be on the same Wi-Fi network.

```bash
cd src/docs
python3 -m http.server 8000
```

Find your computer's local IP (`ipconfig getifaddr en0` on macOS,
`hostname -I` on Linux), then on the iPhone open
`http://<that-ip>:8000`. (Add to Home Screen still works; full PWA install needs
the HTTPS Pages URL from Option A.)

---

## Run it on Android

Because it's a PWA, Android treats it as a first-class app - and because it runs
in real Chrome, **screenshots and cover art are full quality**.

### Easiest - install the PWA (no APK needed)
1. Open the Pages URL in **Chrome** on Android.
2. Tap the **⋮** menu → **Install app** (or **Add to Home screen**).
3. It installs as a standalone app with its own icon, full-screen.

### Get an actual `.apk` file
- **One click (recommended):** go to **https://www.pwabuilder.com**, paste your
  Pages URL, choose **Android**, and **Download** the package. It produces a
  signed `.apk`/`.aab` plus install instructions.
- **From this repo (CI):** the **"Build Android APK"** GitHub Action
  (`.github/workflows/build-android-apk.yml`) wraps the live site into a
  Trusted Web Activity with [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap)
  and uploads the APK as a downloadable artifact. Run it from the **Actions**
  tab → **Run workflow**, then download **`ps-recommender-apk`** from the run and
  sideload it (you'll allow "install from unknown sources"). The TWA config lives
  in `src/android/twa-manifest.json`.

> To hide the small URL bar in a TWA, the APK's signing fingerprint must be
> published in a `/.well-known/assetlinks.json` on the domain. PWABuilder walks
> you through this; for a quick review build it's optional.

---

## How to use it / what to "ask" it

- Start typing a game you love (e.g. **God of War**, **Elden Ring**) - pick
  from the suggestions - or upload a **photo/screenshot** and let the closest
  visual match seed everything.
- See its rating, studio, genres/themes, summary and screenshots (tap a shot to
  enlarge).
- Tap **See 12 recommendations**, then switch between the **Smart**,
  **Looks alike** and **Hidden gems** tabs. Press & hold any card to peek at
  its screenshots.
- Tap a recommendation to open it; the **"Why we picked this"** panel explains
  the match. Recommend again from there to keep exploring.
- Check **Upcoming** for what's next, keep favourites in **My List**, and tap
  **Share** to send the list via the native share sheet.

## What's in here

| File | Purpose |
|---|---|
| `index.html` | App shell / screens + gallery & lightbox markup |
| `styles.css` | Mobile-first PlayStation theme, iPhone safe-area aware |
| `app.js` | Autocomplete, detail, tabs, photo search, why-panel, My List |
| `config.js` | Public Supabase URL + publishable (anon) key |
| `manifest.webmanifest` | Makes it an installable app (name, icons, colors) |
| `sw.js` | Service worker - installability + offline shell + cover cache |
| `icons/` | Home-screen app icons |
| `models/` | ONNX copy of the vision model, committed by CI |
| `screenshots/` | App screenshots embedded in the top-level README |
| `test/` | Headless verification of the full flow (`npm test`) |

## The key is safe to ship

`config.js` holds the Supabase **publishable / anon** key. It's designed to live
in clients: Row-Level Security allows anonymous **reads only** on every table,
so the key cannot change or delete any data.

## Verify it yourself

```bash
cd src/docs/test
npm install
npm test
```

This loads the real page, feeds it the exact payloads the live database returns
for a "God of War" search, and asserts that autocomplete, the screenshot
gallery, the 12 recommendations, the "why we picked this" panel, and the
full-quality lightbox all render correctly.

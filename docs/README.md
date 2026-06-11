# PlayStation Game Recommender — iPhone & Android app

This folder is a complete, installable **mobile app** (a Progressive Web App).
It installs to your Home Screen with its own icon, runs full-screen with no
browser chrome, and works offline for the shell.

It gives **real results**: it calls the same live Supabase backend the desktop
app uses — the 3,840 PS4/PS5 games collected by `igdb_data_collection.ipynb` —
through the `search_games` and `get_recommendations` database functions. Cover
art and screenshots are streamed from the IGDB CDN.

### What it does
- **Type-ahead search** — suggestions appear as you type ("God of…" → all the
  God of War games, etc.).
- **Detail screen** — cover, rating, studio, genres/themes, summary, and a
  **screenshot gallery** (tap any shot for a full-quality, swipeable lightbox).
- **12 recommendations** — **press & hold** a card to peek at in-game
  screenshots; tap to open it.
- **"Why we picked this for you"** — on a recommended game, an explanation panel
  shows the exact reasons (shared studio / genres / themes / direct-similarity)
  and how the engine scores them.
- **Share** the list via the native share sheet.

```
Type a game you love → details + screenshots → 12 recommendations (with "why") → share
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

## Run it on Android

Because it's a PWA, Android treats it as a first-class app — and because it runs
in real Chrome, **screenshots and cover art are full quality**.

### Easiest — install the PWA (no APK needed)
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
  in `android/twa-manifest.json`.

> To hide the small URL bar in a TWA, the APK's signing fingerprint must be
> published in a `/.well-known/assetlinks.json` on the domain. PWABuilder walks
> you through this; for a quick review build it's optional.

---

## How to use it / what to "ask" it

- Start typing a game you love (e.g. **God of War**, **Elden Ring**) — pick from
  the suggestions that appear.
- See its rating, studio, genres/themes, summary and screenshots (tap a shot to
  enlarge).
- Tap **See 12 recommendations** — the engine finds the most similar PS4/PS5
  games. Press & hold any card to peek at its screenshots.
- Tap a recommendation to open it; the **"Why we picked this"** panel explains
  the match. Recommend again from there to keep exploring.
- Tap **Share** to send the list via the native share sheet.

## What's in here

| File | Purpose |
|---|---|
| `index.html` | App shell / screens + gallery & lightbox markup |
| `styles.css` | Mobile-first PlayStation theme, iPhone safe-area aware |
| `app.js` | Autocomplete, detail, gallery, why-panel, recommendations |
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
cd docs/test
npm install
npm test
```

This loads the real page, feeds it the exact payloads the live database returns
for a "God of War" search, and asserts that autocomplete, the screenshot
gallery, the 12 recommendations, the "why we picked this" panel, and the
full-quality lightbox all render correctly.

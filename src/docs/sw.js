/*
 * Service worker - makes the app installable and lets the shell load offline.
 * Strategy:
 *   - App shell (HTML/CSS/JS/icons): network-first with cache fallback, so
 *     users always get the latest build online but can still open the app
 *     offline. index.html is the offline fallback for any same-origin miss.
 *   - IGDB image CDN (images.igdb.com/.../<image_id>.jpg): cache-first with
 *     an LRU cap. Every URL is content-addressed by IGDB's image_id, so a
 *     cached copy is always fresh - hitting the network is pure waste.
 *   - Everything else (Supabase API, transformers.js model, fonts): straight
 *     to network - the browser HTTP cache handles those and we do not want
 *     to serve stale RPC data.
 * Bump the version numbers below to invalidate all caches on the next SW
 * install.
 */
var SHELL = "ps-recommender-shell-v23";
var RUNTIME = "ps-recommender-runtime-v23";
var RUNTIME_MAX_ENTRIES = 150; // ~150 cover/screenshot thumbnails (< 20 MB)

var SHELL_ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./config.js",
  "./app.js",
  "./ps-finder-logo.svg",
  "./manifest.webmanifest",
  "./icons/icon-180.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-512-maskable.png",
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(SHELL).then(function (c) { return c.addAll(SHELL_ASSETS); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== SHELL && k !== RUNTIME) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

// Best-effort LRU trim: caches don't expose access-time, so we just keep
// the cache from growing without bound by dropping the oldest keys once
// we cross the ceiling. Called after each RUNTIME put.
function trimRuntime() {
  caches.open(RUNTIME).then(function (c) {
    c.keys().then(function (keys) {
      var excess = keys.length - RUNTIME_MAX_ENTRIES;
      if (excess <= 0) return;
      for (var i = 0; i < excess; i++) c.delete(keys[i]);
    });
  });
}

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;

  var url = new URL(req.url);

  // Same-origin (the shell): network-first, cache fallback, index.html
  // as the last-resort offline shell.
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(SHELL).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) { return hit || caches.match("./index.html"); });
      })
    );
    return;
  }

  // IGDB image CDN: cache-first (URLs are content-addressed, never change).
  // Saves one network round-trip per cover/screenshot after the first view.
  if (url.hostname.indexOf("images.igdb.com") !== -1) {
    e.respondWith(
      caches.match(req).then(function (hit) {
        if (hit) return hit;
        return fetch(req).then(function (res) {
          if (res.ok) {
            var copy = res.clone();
            caches.open(RUNTIME).then(function (c) {
              c.put(req, copy).then(trimRuntime);
            });
          }
          return res;
        }).catch(function () { return caches.match(req); });
      })
    );
    return;
  }
  // Supabase API, transformers.js CDN, fonts, everything else -> network.
});

/*
 * Service worker — makes the app installable and lets the shell load offline.
 * Strategy:
 *   - App shell (HTML/CSS/JS/icons): cache-first, so the app opens instantly
 *     and works with no connection (data calls still need the network).
 *   - Everything else (Supabase API, IGDB cover images): network-first with a
 *     runtime cache fallback, so previously seen covers survive offline.
 */
var SHELL = "ps-recommender-shell-v10";
var RUNTIME = "ps-recommender-runtime-v10";

var SHELL_ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./config.js",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon-180.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
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

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;

  var url = new URL(req.url);
  var isShell = url.origin === self.location.origin &&
    SHELL_ASSETS.indexOf("." + url.pathname.replace(self.registration.scope.replace(self.location.origin, ""), "/")) !== -1;

  // Same-origin shell → cache-first.
  if (url.origin === self.location.origin) {
    e.respondWith(
      caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (res) {
          var copy = res.clone();
          caches.open(SHELL).then(function (c) { c.put(req, copy); });
          return res;
        }).catch(function () { return caches.match("./index.html"); });
      })
    );
    return;
  }

  // Cover images → cache them after first view (network-first).
  if (url.hostname.indexOf("images.igdb.com") !== -1) {
    e.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(RUNTIME).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () { return caches.match(req); })
    );
    return;
  }
  // Supabase API and anything else → straight to network.
});

/*
 * PlayStation Game Recommender — iPhone PWA front-end.
 *
 * Talks directly to the Supabase PostgREST API (same backend + data as the
 * desktop app and the IGDB notebook). No framework, no build step — just a
 * static page that any phone can open and "Add to Home Screen".
 *
 * Flow:  Search  →  Detail  →  9 Recommendations  →  (drill in / share)
 */
(function () {
  "use strict";

  var CFG = window.APP_CONFIG || {};
  var URL_BASE = CFG.SUPABASE_URL;
  var KEY = CFG.SUPABASE_KEY;

  // IGDB CDN cover art. Sizes: t_cover_big (264x374), t_cover_small (90x128).
  function cover(id, size) {
    return "https://images.igdb.com/igdb/image/upload/t_" + (size || "cover_big") + "/" + id + ".jpg";
  }

  var GAME_COLS =
    "id,name,release_year,total_rating,cover_id,summary,genres,themes,developers,publishers";

  // ---------- tiny REST client -------------------------------------------
  function headers() {
    return {
      apikey: KEY,
      Authorization: "Bearer " + KEY,
      "Content-Type": "application/json",
      Accept: "application/json",
    };
  }

  function rpc(fn, body) {
    return fetch(URL_BASE + "/rest/v1/rpc/" + fn, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(body),
    }).then(checkJson);
  }

  function getGame(id) {
    var url =
      URL_BASE + "/rest/v1/games?id=eq." + encodeURIComponent(id) +
      "&select=" + encodeURIComponent(GAME_COLS) + "&limit=1";
    return fetch(url, { headers: headers() })
      .then(checkJson)
      .then(function (rows) { return rows && rows[0]; });
  }

  function checkJson(r) {
    if (!r.ok) {
      return r.text().then(function (t) {
        throw new Error("Server " + r.status + (t ? ": " + t.slice(0, 120) : ""));
      });
    }
    return r.json();
  }

  function searchGames(q) { return rpc("search_games", { q: q, lim: 12 }); }
  function recommend(id) { return rpc("get_recommendations", { source_id: id, lim: 9 }); }

  // ---------- helpers -----------------------------------------------------
  function $(sel) { return document.querySelector(sel); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function rating(v) {
    var n = parseFloat(v);
    return isFinite(n) ? String(Math.round(n)) : null;
  }
  function arr(v) { return Array.isArray(v) ? v : []; }

  var spinnerCount = 0;
  function showSpinner(on) {
    spinnerCount = Math.max(0, spinnerCount + (on ? 1 : -1));
    var s = $("#spinner");
    if (s) s.hidden = spinnerCount === 0;
  }
  var toastTimer;
  function toast(msg) {
    var t = $("#toast");
    if (!t) return;
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 2200);
  }

  // ---------- navigation --------------------------------------------------
  function show(view) {
    var views = document.querySelectorAll(".view");
    for (var i = 0; i < views.length; i++) views[i].classList.remove("active");
    var v = $("#view-" + view);
    if (v) v.classList.add("active");
    window.scrollTo(0, 0);
  }

  // ---------- cover image with graceful placeholder -----------------------
  function coverImg(game, size, w, h) {
    var wrap = el("div", "cover");
    wrap.style.aspectRatio = (w || 264) + " / " + (h || 374);
    var letter = (game.name || "?").trim().charAt(0).toUpperCase() || "?";
    wrap.appendChild(el("span", "cover-ph", letter));
    if (game.cover_id) {
      var img = new Image();
      img.alt = game.name || "";
      img.loading = "lazy";
      img.decoding = "async";
      img.onload = function () { wrap.classList.add("loaded"); };
      img.src = cover(game.cover_id, size || "cover_big");
      wrap.appendChild(img);
    }
    return wrap;
  }

  // ---------- HOME --------------------------------------------------------
  function initHome() {
    var form = $("#search-form");
    var input = $("#search-input");
    var status = $("#search-status");
    var list = $("#results");

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value.trim();
      if (q.length < 2) { return; }
      input.blur();
      list.hidden = true;
      list.innerHTML = "";
      status.hidden = false;
      status.textContent = "Searching…";
      showSpinner(true);

      searchGames(q)
        .then(function (matches) {
          showSpinner(false);
          if (!matches || !matches.length) {
            status.textContent = "No games found for “" + q + "”.";
            return;
          }
          if (matches.length === 1) { openDetail(matches[0].id); return; }
          status.hidden = true;
          renderResults(matches, list);
        })
        .catch(function (err) {
          showSpinner(false);
          status.textContent = "Couldn't reach the server. Check your connection.";
          console.error(err);
        });
    });
  }

  function renderResults(matches, list) {
    list.innerHTML = "";
    matches.forEach(function (g) {
      var li = el("li", "result");
      li.appendChild(coverImg(g, "cover_small", 90, 128));
      var meta = el("div", "result-meta");
      meta.appendChild(el("div", "result-name", g.name));
      var sub = [];
      if (g.release_year) sub.push(String(g.release_year));
      var r = rating(g.total_rating);
      if (r) sub.push("★ " + r);
      meta.appendChild(el("div", "result-sub", sub.join("   ·   ")));
      li.appendChild(meta);
      li.addEventListener("click", function () { openDetail(g.id); });
      list.appendChild(li);
    });
    list.hidden = false;
  }

  // ---------- DETAIL ------------------------------------------------------
  var currentGame = null;

  function openDetail(id) {
    showSpinner(true);
    getGame(id)
      .then(function (game) {
        showSpinner(false);
        if (!game) { toast("That game isn't in the dataset."); return; }
        currentGame = game;
        renderDetail(game);
        show("detail");
      })
      .catch(function (err) {
        showSpinner(false);
        toast("Network error.");
        console.error(err);
      });
  }

  function renderDetail(game) {
    var body = $("#detail-body");
    body.innerHTML = "";

    body.appendChild(coverImg(game, "cover_big", 264, 374));

    var info = el("div", "detail-info");
    info.appendChild(el("h2", "detail-title", game.name));

    var meta = [];
    if (game.release_year) meta.push(String(game.release_year));
    if (arr(game.developers).length) meta.push(arr(game.developers).slice(0, 2).join(", "));
    info.appendChild(el("p", "detail-meta", meta.join("  ·  ")));

    var r = rating(game.total_rating);
    var ratingRow = el("div", "rating-row");
    ratingRow.appendChild(el("span", "rating-num", r || "—"));
    ratingRow.appendChild(el("span", "rating-label", "RATING / 100"));
    info.appendChild(ratingRow);

    var chips = el("div", "chips");
    arr(game.genres).slice(0, 3).concat(arr(game.themes).slice(0, 2)).forEach(function (t) {
      chips.appendChild(el("span", "chip", t));
    });
    if (chips.childNodes.length) info.appendChild(chips);

    info.appendChild(el("p", "summary", game.summary || "No summary available."));

    var cta = el("button", "btn-primary btn-block", "See 9 recommendations  →");
    cta.addEventListener("click", function () { openRecs(game); });
    info.appendChild(cta);

    body.appendChild(info);
  }

  // ---------- RECOMMENDATIONS --------------------------------------------
  var currentRecs = [];

  function openRecs(source) {
    showSpinner(true);
    recommend(source.id)
      .then(function (recs) {
        showSpinner(false);
        if (!recs || !recs.length) { toast("Couldn't generate recommendations."); return; }
        currentRecs = recs;
        $("#recs-heading").textContent = "Because you like “" + source.name + "”";
        renderRecs(recs);
        show("recs");
      })
      .catch(function (err) {
        showSpinner(false);
        toast("Network error.");
        console.error(err);
      });
  }

  function renderRecs(recs) {
    var grid = $("#recs-grid");
    grid.innerHTML = "";
    recs.forEach(function (g) {
      var card = el("button", "card");
      card.appendChild(coverImg(g, "cover_big", 160, 226));
      card.appendChild(el("div", "card-name", g.name));
      var sub = [];
      if (g.release_year) sub.push(String(g.release_year));
      var r = rating(g.total_rating);
      if (r) sub.push("★ " + r);
      if (arr(g.genres).length) sub.push(arr(g.genres)[0]);
      card.appendChild(el("div", "card-sub", sub.join("  ·  ")));
      card.addEventListener("click", function () { openDetail(g.id); });
      grid.appendChild(card);
    });
  }

  function shareText() {
    if (!currentGame) return "";
    var lines = ["Because I love " + currentGame.name + ", I should play:"];
    currentRecs.forEach(function (g, i) {
      var bits = (i + 1) + ". " + g.name;
      if (g.release_year) bits += " (" + g.release_year + ")";
      var r = rating(g.total_rating);
      if (r) bits += " — ★ " + r + "/100";
      lines.push(bits);
    });
    lines.push("");
    lines.push("via PlayStation Game Recommender");
    return lines.join("\n");
  }

  function doShare() {
    var text = shareText();
    if (!text) return;
    if (navigator.share) {
      navigator.share({ title: "Game recommendations", text: text }).catch(function () {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () { toast("Copied to clipboard!"); });
    } else {
      toast("Sharing not supported.");
    }
  }

  // ---------- wire-up -----------------------------------------------------
  function init() {
    if (!URL_BASE || !KEY) {
      alert("Missing backend config (config.js).");
      return;
    }
    initHome();

    document.querySelectorAll("[data-nav]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var t = btn.getAttribute("data-nav");
        if (t === "home") show("home");
        else if (t === "back-detail") show("detail");
      });
    });

    var share = $("#share-btn");
    if (share) share.addEventListener("click", doShare);

    show("home");

    if ("serviceWorker" in navigator) {
      window.addEventListener("load", function () {
        navigator.serviceWorker.register("sw.js").catch(function () {});
      });
    }
  }

  // Expose a few internals so an automated test can drive the app.
  window.__app = {
    openDetail: openDetail,
    openRecs: openRecs,
    shareText: shareText,
    setConfig: function (c) { URL_BASE = c.SUPABASE_URL; KEY = c.SUPABASE_KEY; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

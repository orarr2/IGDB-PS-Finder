/*
 * PlayStation Game Recommender - iPhone/Android PWA front-end.
 *
 * Talks directly to the Supabase PostgREST API (same backend + data as the
 * IGDB notebook). No framework, no build step.
 *
 * Features:
 *   - Live autocomplete as you type
 *   - Rich detail screen: cover, rating, genres/themes, summary, screenshot
 *     gallery (tap for full-quality lightbox)
 *   - 12 recommendations; press & hold a card to peek at in-game screenshots
 *   - On a recommended game's detail: a "Why we picked this for you" panel that
 *     explains the match using the same logic the recommendation engine scores
 */
(function () {
  "use strict";

  var CFG = window.APP_CONFIG || {};
  var URL_BASE = CFG.SUPABASE_URL;
  var KEY = CFG.SUPABASE_KEY;

  var REC_COUNT = 12; // at least 10 recommendations

  // IGDB CDN. https://images.igdb.com/igdb/image/upload/t_<size>/<id>.jpg
  function img(id, size) {
    return "https://images.igdb.com/igdb/image/upload/t_" + size + "/" + id + ".jpg";
  }
  function cover(id, size) { return img(id, size || "cover_big"); }
  function shot(id, size) { return img(id, size || "screenshot_med"); }

  var GAME_COLS = [
    "id", "name", "release_year", "total_rating", "cover_id", "summary",
    "genres", "themes", "developers", "publishers",
    "game_modes", "similar_games", "screenshot_ids", "artwork_ids",
    "franchises", "collections",
  ].join(",");

  // ---------- REST ----------
  function headers() {
    return {
      apikey: KEY, Authorization: "Bearer " + KEY,
      "Content-Type": "application/json", Accept: "application/json",
    };
  }
  function checkJson(r) {
    if (!r.ok) return r.text().then(function (t) { throw new Error("Server " + r.status + (t ? ": " + t.slice(0, 120) : "")); });
    return r.json();
  }
  function rpc(fn, body) {
    return fetch(URL_BASE + "/rest/v1/rpc/" + fn, { method: "POST", headers: headers(), body: JSON.stringify(body) }).then(checkJson);
  }
  function getGame(id) {
    var u = URL_BASE + "/rest/v1/games?id=eq." + encodeURIComponent(id) + "&select=" + encodeURIComponent(GAME_COLS) + "&limit=1";
    return fetch(u, { headers: headers() }).then(checkJson).then(function (rows) { return rows && rows[0]; });
  }
  function searchGames(q, lim) { return rpc("search_games", { q: q, lim: lim || 8 }); }
  // Other titles in the same series. Combines two signals so coverage is as
  // complete as the data allows:
  //   1. IGDB franchise/collection tag (accurate; collection preferred so a broad
  //      franchise like "Marvel" doesn't drag in every Marvel game)
  //   2. shared base name (catches siblings that exist but are mistagged, e.g.
  //      "Uncharted 4" → other "Uncharted …" titles)
  function arrLit(list) {
    return "{" + list.map(function (s) { return '"' + String(s).replace(/(["\\])/g, "\\$1") + '"'; }).join(",") + "}";
  }
  function seriesBase(name) {
    var n = (name || "").split(/[:(]|\s-\s/)[0].trim();   // split off subtitle after ":", "(", or " - "
    n = n.replace(/\s+\b([IVX]{1,4}|\d{1,2})\b\s*$/i, "").trim();      // drop trailing volume number
    return n;
  }
  function seriesGames(source) {
    if (!source) return Promise.resolve([]);
    function tagRows(s) {
      var co = arr(s.collections), fr = arr(s.franchises);
      var key = co.length ? co : fr;
      var col = co.length ? "collections" : "franchises";
      if (!key.length) return Promise.resolve([]);
      var u = URL_BASE + "/rest/v1/games?" + col + "=ov." + encodeURIComponent(arrLit(key)) +
        "&select=" + encodeURIComponent(GAME_COLS) + "&order=release_year.asc&limit=24";
      return fetch(u, { headers: headers() }).then(checkJson).catch(function () { return []; });
    }
    function nameRows(s) {
      var base = seriesBase(s.name);
      if (base.length < 4) return Promise.resolve([]);
      var u = URL_BASE + "/rest/v1/games?name=ilike." + encodeURIComponent(base + "*") +
        "&select=" + encodeURIComponent(GAME_COLS) + "&order=release_year.asc&limit=24";
      return fetch(u, { headers: headers() }).then(checkJson).catch(function () { return []; });
    }
    function run(s) {
      return Promise.all([tagRows(s), nameRows(s)]).then(function (res) {
        var seen = {}, out = [];
        res[0].concat(res[1]).forEach(function (g) {
          if (g && g.id != null && !seen[g.id]) { seen[g.id] = 1; out.push(g); }
        });
        out.sort(function (a, b) { return (a.release_year || 0) - (b.release_year || 0); });
        return out;
      });
    }
    // A source from a recommendation card may lack franchise fields - enrich first.
    if (source.collections === undefined && source.franchises === undefined) {
      return getGame(source.id).then(run).catch(function () { return []; });
    }
    return run(source);
  }
  function recommend(id) { return rpc("get_recommendations", { source_id: id, lim: REC_COUNT }); }
  function recommendVisual(id) { return rpc("get_visual_recommendations", { source_id: id, lim: REC_COUNT }); }
  function recommendGems(id) { return rpc("get_hidden_gems", { source_id: id, lim: REC_COUNT }); }
  function userMedia(id) {
    var cols = "source,image_url,thumb_url,author,source_url,caption";
    var u = URL_BASE + "/rest/v1/user_media?game_id=eq." + encodeURIComponent(id) +
      "&select=" + encodeURIComponent(cols) + "&limit=12";
    return fetch(u, { headers: headers() }).then(checkJson);
  }
  // visual-similarity cosine scores for a source game's neighbours → {id: cos}
  function fetchVisScores(id) {
    var u = URL_BASE + "/rest/v1/visual_neighbors?game_id=eq." + encodeURIComponent(id) +
      "&select=neighbor_ids,scores&limit=1";
    return fetch(u, { headers: headers() }).then(checkJson).then(function (rows) {
      var map = {};
      if (rows && rows[0]) {
        var ids = rows[0].neighbor_ids || [], sc = rows[0].scores || [];
        for (var i = 0; i < ids.length; i++) map[String(ids[i])] = sc[i];
      }
      return map;
    }).catch(function () { return {}; });
  }

  // ---------- helpers ----------
  function $(s) { return document.querySelector(s); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function rating(v) { var n = parseFloat(v); return isFinite(n) ? String(Math.round(n)) : null; }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function intersect(a, b) { var B = arr(b); return arr(a).filter(function (x) { return B.indexOf(x) !== -1; }); }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function listText(items, max) {
    items = items.slice(0, max || 3);
    if (items.length === 1) return items[0];
    if (items.length === 2) return items[0] + " and " + items[1];
    return items.slice(0, -1).join(", ") + ", and " + items[items.length - 1];
  }

  var spin = 0;
  function showSpinner(on) { spin = Math.max(0, spin + (on ? 1 : -1)); var s = $("#spinner"); if (s) s.hidden = spin === 0; }
  var toastT;
  function toast(m) { var t = $("#toast"); if (!t) return; t.textContent = m; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(function () { t.hidden = true; }, 2200); }

  // ---------- pill button (colored glyph + label in one button) ----------
  function pillBtn(kind, glyph, label) {
    var b = el("button", "pbtn pbtn-" + kind);
    b.type = "button";
    b.appendChild(el("span", "g", glyph));
    b.appendChild(document.createTextNode(" " + label));
    return b;
  }

  // ---------- "My List" (□ Save) - persisted locally on the device ----------
  var SAVE_KEY = "psf_saved";
  function getSaved() { try { return JSON.parse(localStorage.getItem(SAVE_KEY)) || []; } catch (e) { return []; } }
  function isSaved(id) { return getSaved().some(function (g) { return g.id === id; }); }
  function toggleSave(game) {
    var list = getSaved(), i = -1;
    for (var k = 0; k < list.length; k++) { if (list[k].id === game.id) { i = k; break; } }
    if (i >= 0) { list.splice(i, 1); toast("Removed from My List"); }
    else {
      list.unshift({ id: game.id, name: game.name, cover_id: game.cover_id,
        release_year: game.release_year, total_rating: game.total_rating, genres: game.genres });
      toast("Saved to My List");
    }
    try { localStorage.setItem(SAVE_KEY, JSON.stringify(list)); } catch (e) {}
    return i < 0;
  }
  function shareGame(game) {
    var t = "Check out " + game.name + (game.release_year ? " (" + game.release_year + ")" : "") +
      " - via PlayStation Game Recommender";
    if (navigator.share) navigator.share({ title: game.name, text: t }).catch(function () {});
    else if (navigator.clipboard) navigator.clipboard.writeText(t).then(function () { toast("Copied to clipboard!"); });
    else toast("Sharing not supported.");
  }

  // ---------- navigation (simple stack) ----------
  var stack = ["home"];
  function show(view) { hidePreview(); document.querySelectorAll(".view").forEach(function (v) { v.classList.remove("active"); }); var v = $("#view-" + view); if (v) v.classList.add("active"); window.scrollTo(0, 0); }
  function push(view) { stack.push(view); show(view); }
  function back() {
    if (stack.length > 1) stack.pop();
    var v = stack[stack.length - 1];
    if (v === "home") resetHome();
    show(v);
  }
  function goHome() { stack = ["home"]; resetHome(); show("home"); }

  // ---------- cover element ----------
  function coverEl(game, size, ratioW, ratioH) {
    var wrap = el("div", "cover");
    wrap.style.aspectRatio = (ratioW || 264) + " / " + (ratioH || 374);
    wrap.appendChild(el("span", "cover-ph", ((game.name || "?").trim().charAt(0) || "?").toUpperCase()));
    if (game.cover_id) {
      var i = new Image();
      i.alt = game.name || ""; i.loading = "lazy"; i.decoding = "async";
      i.onload = function () { wrap.classList.add("loaded"); };
      i.src = cover(game.cover_id, size || "cover_big");
      wrap.appendChild(i);
    }
    return wrap;
  }

  // ============================================================ HOME
  var suggestT, lastQ = "";
  function resetHome() {
    var inp = $("#search-input"); if (inp) inp.value = "";
    var s = $("#suggest"); if (s) { s.hidden = true; s.innerHTML = ""; }
    var st = $("#search-status"); if (st) st.hidden = true;
  }

  function initHome() {
    var form = $("#search-form");
    var input = $("#search-input");
    var status = $("#search-status");
    var sug = $("#suggest");

    input.addEventListener("input", function () {
      var q = (input.value || "").trim();
      status.hidden = true;
      clearTimeout(suggestT);
      if (q.length < 2) { sug.hidden = true; sug.innerHTML = ""; return; }
      suggestT = setTimeout(function () { runSuggest(q); }, 200);
    });

    // Pressing enter: open the top suggestion, else run a search.
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      clearTimeout(suggestT);
      var q = (input.value || "").trim();
      if (q.length < 2) return;
      var first = sug.querySelector(".suggest-item");
      if (first && first.dataset.id) { openPick(parseInt(first.dataset.id, 10)); return; }
      runSuggest(q, true);
    });

    // hide suggestions when tapping away
    document.addEventListener("click", function (e) {
      if (!e.target.closest("#search-form")) sug.hidden = true;
    });

    // search by photo
    var pbtn = $("#photo-btn"), pin = $("#photo-input");
    if (pbtn && pin) {
      pbtn.addEventListener("click", function () { loadEmbedder().catch(function () {}); pin.value = ""; pin.click(); });
      pin.addEventListener("change", function () { handlePhoto(pin.files && pin.files[0]); });
    }
  }

  function runSuggest(q, openIfSingle) {
    lastQ = q;
    searchGames(q, 8).then(function (matches) {
      if (lastQ !== q) return; // a newer query superseded this one
      var sug = $("#suggest");
      var status = $("#search-status");
      if (!matches || !matches.length) {
        sug.hidden = true; sug.innerHTML = "";
        status.hidden = false; status.textContent = "No games found for “" + q + "”.";
        return;
      }
      if (openIfSingle && matches.length === 1) { openPick(matches[0].id); return; }
      renderSuggest(matches);
    }).catch(function (err) {
      console.error(err);
      $("#search-status").hidden = false; $("#search-status").textContent = "Couldn't reach the server.";
    });
  }

  function renderSuggest(matches) {
    var sug = $("#suggest");
    sug.innerHTML = "";
    matches.forEach(function (g) {
      var li = el("li", "suggest-item");
      li.dataset.id = g.id;
      li.appendChild(coverEl(g, "cover_small", 90, 128));
      var meta = el("div", "suggest-meta");
      meta.appendChild(el("div", "suggest-name", g.name));
      var sub = [];
      if (g.release_year) sub.push(String(g.release_year));
      var r = rating(g.total_rating); if (r) sub.push("★ " + r);
      meta.appendChild(el("div", "suggest-sub", sub.join("   ·   ")));
      li.appendChild(meta);
      li.addEventListener("click", function () { openPick(g.id); });
      sug.appendChild(li);
    });
    sug.hidden = false;
  }

  // ============================================================ DETAIL
  // sourceGame = the game whose recommendations we're currently exploring.
  var sourceGame = null;

  function openPick(id) {
    showSpinner(true);
    getGame(id).then(function (game) {
      showSpinner(false);
      if (!game) { toast("That game isn't in the dataset."); return; }
      renderDetail(game, null);
      push("detail");
    }).catch(function (err) { showSpinner(false); toast("Network error."); console.error(err); });
  }

  // whyAgainst: when set, render the "why recommended" panel relative to it.
  // mode: "smart" (tag match) or "visual" (look-alike) - changes the explanation.
  function openDetail(game, whyAgainst, mode) {
    renderDetail(game, whyAgainst || null, mode || "smart");
    push("detail");
  }

  function renderDetail(game, whyAgainst, mode) {
    var body = $("#detail-body");
    body.innerHTML = "";

    var head = el("div", "detail-head");
    head.appendChild(coverEl(game, "cover_big", 264, 374));

    var info = el("div", "detail-info");
    info.appendChild(el("h2", "detail-title", game.name));
    var meta = [];
    if (game.release_year) meta.push(String(game.release_year));
    if (arr(game.developers).length) meta.push(arr(game.developers).slice(0, 2).join(", "));
    info.appendChild(el("p", "detail-meta", meta.join("  ·  ")));

    var r = rating(game.total_rating);
    var rr = el("div", "rating-row");
    rr.appendChild(el("span", "rating-num", r || "-"));
    rr.appendChild(el("span", "rating-label", "RATING / 100"));
    info.appendChild(rr);

    var chips = el("div", "chips");
    arr(game.genres).slice(0, 3).concat(arr(game.themes).slice(0, 2)).forEach(function (t) { chips.appendChild(el("span", "chip", t)); });
    if (chips.childNodes.length) info.appendChild(chips);

    head.appendChild(info);
    body.appendChild(head);

    // WHY panel - right after the score & genres, before the summary.
    if (whyAgainst) body.appendChild(whyPanel(game, whyAgainst, mode));

    if (game.summary) {
      var sec = el("div", "section");
      sec.appendChild(el("h3", "section-h", "About"));
      sec.appendChild(el("p", "summary", game.summary));
      body.appendChild(sec);
    }

    // Screenshot gallery (full-quality lightbox on tap).
    var shots = arr(game.screenshot_ids);
    if (shots.length) {
      var gsec = el("div", "section");
      gsec.appendChild(el("h3", "section-h", "Screenshots"));
      var strip = el("div", "gallery");
      shots.forEach(function (sid, idx) {
        var cell = el("button", "shot");
        var im = new Image();
        im.alt = game.name + " screenshot " + (idx + 1);
        im.loading = "lazy"; im.decoding = "async";
        im.onload = function () { cell.classList.add("loaded"); };
        im.src = shot(sid, "screenshot_med");
        cell.appendChild(im);
        cell.addEventListener("click", function () { openLightbox(shots, idx, game.name); });
        strip.appendChild(cell);
      });
      gsec.appendChild(strip);
      body.appendChild(gsec);
    }

    // Player captures (Steam Community + Reddit) - links only, loaded async.
    var pcSec = el("div", "section");
    pcSec.hidden = true;
    pcSec.appendChild(el("h3", "section-h", "Player captures · Steam Community"));
    var pcStrip = el("div", "gallery");
    pcSec.appendChild(pcStrip);
    body.appendChild(pcSec);
    loadUserMedia(game, pcSec, pcStrip);

    var actions = el("div", "detail-actions");
    var recBtn = pillBtn("x", "✕", "See " + REC_COUNT + " recommendations");
    recBtn.addEventListener("click", function () { openRecs(game); });
    var saved0 = isSaved(game.id);
    var saveBtn = pillBtn("sq", "□", saved0 ? "Saved" : "Save");
    if (saved0) saveBtn.classList.add("on");
    saveBtn.addEventListener("click", function () {
      var nowSaved = toggleSave(game);
      saveBtn.classList.toggle("on", nowSaved);
      saveBtn.lastChild.textContent = " " + (nowSaved ? "Saved" : "Save");
    });
    var shareBtn = pillBtn("tr", "△", "Share");
    shareBtn.addEventListener("click", function () { shareGame(game); });
    actions.appendChild(recBtn); actions.appendChild(saveBtn); actions.appendChild(shareBtn);
    body.appendChild(actions);
  }

  function loadUserMedia(game, sec, strip) {
    userMedia(game.id).then(function (list) {
      if (!list || !list.length) return; // stays hidden if none
      list.forEach(function (m) {
        var cell = document.createElement("a");
        cell.className = "shot pc-shot";
        cell.href = m.source_url || m.image_url;
        cell.target = "_blank"; cell.rel = "noopener";
        cell.title = (m.caption || "") + (m.author ? "  - " + m.author : "");
        var im = new Image();
        im.alt = m.caption || (game.name + " - player capture");
        im.loading = "lazy"; im.decoding = "async";
        im.onload = function () { cell.classList.add("loaded"); };
        im.onerror = function () {
          cell.remove();
          if (!strip.children.length) sec.hidden = true;
        };
        im.src = m.thumb_url || m.image_url;
        cell.appendChild(im);
        cell.appendChild(el("span", "pc-tag", m.source === "steam" ? "Steam" : "Reddit"));
        strip.appendChild(cell);
      });
      sec.hidden = false;
    }).catch(function () {});
  }

  // ---------- match score (per mode - never blended) ----------
  // Smart  = metadata only: series/IGDB-similar, genres, themes, studio, rating.
  // Visual = gameplay screenshot similarity only (computer vision / cosine).
  // The two are kept strictly separate so the modes don't bleed into each other.
  function matchInfo(rec, src, mode) {
    if (!src) src = {};
    var cos = currentVisScores[String(rec.id)];
    var vis = (typeof cos === "number") ? clamp((cos - 0.5) / 0.45, 0, 1) : null;

    var sg = intersect(rec.genres, src.genres);
    var gMax = Math.min(3, Math.max(1, arr(src.genres).length));
    var genreOverlap = clamp(sg.length / gMax, 0, 1);

    var sth = intersect(rec.themes, src.themes);
    var tMax = Math.min(3, Math.max(1, arr(src.themes).length));
    var themeOverlap = arr(src.themes).length ? clamp(sth.length / tMax, 0, 1) : 0;

    var devs = intersect(rec.developers, src.developers);
    var isSimilar = arr(src.similar_games).map(String).indexOf(String(rec.id)) !== -1;
    var sameSeries = (intersect(rec.collections, src.collections).length > 0) ||
                     (intersect(rec.franchises, src.franchises).length > 0);
    var rNum = parseFloat(rec.total_rating);
    var ratingClose = isFinite(rNum) ? clamp(rNum / 100, 0, 1) : 0;

    var pct;
    if (mode === "visual") {
      pct = vis != null ? vis : 0;                       // look-alike: vision only
    } else {
      pct = clamp(                                        // smart: metadata only
        ((isSimilar || sameSeries) ? 0.45 : 0) +
        0.30 * genreOverlap +
        0.12 * themeOverlap +
        (devs.length ? 0.08 : 0) +
        0.05 * ratingClose, 0, 1);
    }
    return {
      mode: mode === "visual" ? "visual" : "smart",
      pct: Math.round(pct * 100),
      visPct: vis != null ? Math.round(vis * 100) : null,
      genrePct: Math.round(genreOverlap * 100),
      themePct: Math.round(themeOverlap * 100),
      sharedGenres: sg, sharedThemes: sth, sharedDevs: devs,
      isSimilar: isSimilar, sameSeries: sameSeries, ratingPct: Math.round(ratingClose * 100),
    };
  }

  function scoreRow(label, pct, sub) {
    var row = el("div", "score-row");
    row.appendChild(el("span", "score-label", label));
    var bar = el("div", "score-bar");
    var fill = el("div", "score-fill");
    fill.style.width = clamp(pct, 0, 100) + "%";
    bar.appendChild(fill);
    row.appendChild(bar);
    row.appendChild(el("span", "score-val", pct + "%"));
    if (sub) row.appendChild(el("div", "score-sub", sub));
    return row;
  }

  function scoreBlock(rec, src) {
    var mi = rec._match || matchInfo(rec, src, currentMode);
    var wrap = el("div", "score-block");
    var head = el("div", "score-head");
    head.appendChild(el("span", "score-big", mi.pct + "%"));
    var cap = el("span", "score-cap");
    cap.innerHTML = "match with <b>" + esc(src && src.name ? src.name : "your pick") + "</b>";
    head.appendChild(cap);
    wrap.appendChild(head);
    var rows = el("div", "score-rows");
    if (mi.mode === "visual") {
      rows.appendChild(scoreRow("Gameplay look-alike", mi.visPct != null ? mi.visPct : 0,
        "how similar the in-game screenshots are (computer vision)"));
    } else {
      if (mi.isSimilar || mi.sameSeries)
        rows.appendChild(scoreRow("Series / IGDB-similar", 100,
          mi.sameSeries ? "same series" : "flagged as similar by IGDB"));
      rows.appendChild(scoreRow("Shared genres", mi.genrePct,
        mi.sharedGenres.length ? mi.sharedGenres.slice(0, 3).join(", ") : "none in common"));
      if (arr(src.themes).length)
        rows.appendChild(scoreRow("Shared themes", mi.themePct,
          mi.sharedThemes.length ? mi.sharedThemes.slice(0, 3).join(", ") : "none in common"));
      if (mi.sharedDevs && mi.sharedDevs.length)
        rows.appendChild(scoreRow("Same studio", 100, mi.sharedDevs.slice(0, 2).join(", ")));
    }
    wrap.appendChild(rows);
    return wrap;
  }

  // ---------- why-recommended explanation ----------
  function esc(s) { return String(s).replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); }
  function whyPanel(rec, src, mode) {
    if (mode === "gems") return whyPanelGems(rec, src);
    if (mode === "visual") return whyPanelVisual(rec, src);
    var panel = el("div", "why");
    panel.appendChild(el("h3", "why-h", "Why we picked this for you"));
    panel.appendChild(scoreBlock(rec, src));

    var reasons = [];
    var isSimilar = arr(src.similar_games).map(String).indexOf(String(rec.id)) !== -1;
    var devs = intersect(rec.developers, src.developers);
    var genres = intersect(rec.genres, src.genres);
    var themes = intersect(rec.themes, src.themes);
    var modes = intersect(rec.game_modes, src.game_modes);

    if (isSimilar) reasons.push("IGDB lists it as a game <b>directly similar to " + esc(src.name) + "</b> - the strongest possible signal.");
    if (devs.length) reasons.push("Same studio: both come from <b>" + esc(listText(devs, 2)) + "</b>.");
    if (genres.length) reasons.push("Shared genres you liked: <b>" + esc(listText(genres, 3)) + "</b>.");
    if (themes.length) reasons.push("Overlapping themes: <b>" + esc(listText(themes, 3)) + "</b>.");
    if (modes.length) reasons.push("Same way to play: <b>" + esc(listText(modes, 2)) + "</b>.");
    var r = rating(rec.total_rating);
    if (r) reasons.push("It's well-rated (<b>★ " + r + "/100</b>), which nudges it up the list.");
    if (!reasons.length) reasons.push("It scored highly overall against <b>" + esc(src.name) + "</b> on our similarity model.");

    var ul = el("ul", "why-list");
    reasons.forEach(function (txt) { var li = document.createElement("li"); li.innerHTML = txt; ul.appendChild(li); });
    panel.appendChild(ul);

    var note = el("p", "why-note");
    note.innerHTML = "How scoring works: a directly-similar game is worth <b>+1000</b>, each shared developer <b>+15</b>, " +
      "each shared genre <b>+10</b>, theme <b>+5</b>, play-mode <b>+3</b>, plus a small bump for rating. " +
      "The top " + REC_COUNT + " by score become your recommendations.";
    panel.appendChild(note);
    return panel;
  }

  function whyPanelVisual(rec, src) {
    var panel = el("div", "why why-visual");
    panel.appendChild(el("h3", "why-h", "Why it looks like this"));
    panel.appendChild(scoreBlock(rec, src));

    var reasons = [];
    reasons.push("Its <b>in-game screenshots</b> are visually closest to <b>" + esc(src.name) +
      "</b> - matched on actual gameplay frames (not box art) by an image-recognition model.");
    var genres = intersect(rec.genres, src.genres);
    var themes = intersect(rec.themes, src.themes);
    if (genres.length) reasons.push("They also share genres: <b>" + esc(listText(genres, 3)) + "</b>.");
    if (themes.length) reasons.push("…and themes: <b>" + esc(listText(themes, 3)) + "</b>.");

    var ul = el("ul", "why-list");
    reasons.forEach(function (txt) { var li = document.createElement("li"); li.innerHTML = txt; ul.appendChild(li); });
    panel.appendChild(ul);

    var note = el("p", "why-note");
    note.innerHTML = "How it works: every game's gameplay screenshots are passed through a convolutional " +
      "neural network (MobileNetV3) that turns each image into a numeric “visual fingerprint.” " +
      "Games are then ranked by how similar their fingerprints are (cosine similarity). This is the " +
      "computer-vision counterpart to the tag-based <b>Smart match</b>.";
    panel.appendChild(note);
    return panel;
  }

  function whyPanelGems(rec, src) {
    var panel = el("div", "why why-gems");
    panel.appendChild(el("h3", "why-h", "Why this hidden gem"));
    var reasons = [];
    var rc = (typeof rec.total_rating_count === "number") ? rec.total_rating_count : null;
    reasons.push("An <b>under-the-radar</b> title" + (rc != null ? " (only <b>" + rc + " reviews</b>)" : "") +
      " whose gameplay looks &amp; feels like <b>" + esc(src && src.name ? src.name : "your pick") + "</b>.");
    var genres = intersect(rec.genres, src ? src.genres : []);
    if (genres.length) reasons.push("Shared genres: <b>" + esc(listText(genres, 3)) + "</b>.");
    var ul = el("ul", "why-list");
    reasons.forEach(function (t) { var li = document.createElement("li"); li.innerHTML = t; ul.appendChild(li); });
    panel.appendChild(ul);
    var note = el("p", "why-note");
    note.innerHTML = "Hidden gems = nearest matches in the <b>CLIP</b> gameplay-vision space, restricted to " +
      "low-popularity games - discovery without bestseller bias.";
    panel.appendChild(note);
    return panel;
  }

  // ============================================================ RECOMMENDATIONS
  var currentRecs = [];
  var currentMode = "visual";
  var currentVisScores = {};
  var currentSeries = [];

  function setActiveSeg(mode) {
    document.querySelectorAll("#rec-mode .seg").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });
  }

  function renderSourceBar(game, html) {
    var bar = $("#rec-source");
    if (!bar) return;
    bar.innerHTML = "";
    if (game) bar.appendChild(coverEl(game, "cover_small", 90, 128));
    bar.appendChild(el("div", "rec-source-text")).innerHTML = html;
    bar.hidden = false;
  }

  function openRecs(source) {
    sourceGame = source;
    renderSourceBar(source, "Recommendations for<br><b>" + esc(source.name) + "</b>");
    var seg = $("#rec-mode"); if (seg) seg.hidden = false;
    var subEl = document.querySelector(".recs-sub"); if (subEl) subEl.hidden = false;
    push("recs");
    // Look-alike (visual) is the headline mode; grab its cosine scores first.
    // Same-series titles are fetched alongside so fans see sequels/spin-offs up top.
    showSpinner(true);
    Promise.all([fetchVisScores(source.id), seriesGames(source)]).then(function (res) {
      currentVisScores = res[0] || {};
      var seen = {};
      currentSeries = (res[1] || []).filter(function (g) {
        if (g.id === source.id || seen[g.id]) return false;
        seen[g.id] = 1; return true;
      });
      showSpinner(false);
      var hasVisual = Object.keys(currentVisScores).length > 0;
      setActiveSeg(hasVisual ? "visual" : "smart");
      loadMode(hasVisual ? "visual" : "smart");
    });
  }

  function loadMode(mode) {
    currentMode = mode;
    var grid = $("#recs-grid"), note = $("#recs-note");
    grid.innerHTML = "";
    note.hidden = true;
    showSpinner(true);
    var p = mode === "visual" ? recommendVisual(sourceGame.id)
          : mode === "gems" ? recommendGems(sourceGame.id)
          : recommend(sourceGame.id);
    p.then(function (recs) {
      showSpinner(false);
      currentRecs = recs || [];
      if (!currentRecs.length) {
        if (mode === "visual") { setActiveSeg("smart"); loadMode("smart"); return; }
        note.hidden = false;
        note.innerHTML = mode === "gems"
          ? "No under-the-radar look-alikes for this one - try <b>Looks alike</b>."
          : "Couldn't generate recommendations.";
        return;
      }
      renderRecs(currentRecs, mode);
    }).catch(function (err) { showSpinner(false); toast("Network error."); console.error(err); });
  }

  function ratingClass(r) { return r == null ? "lo" : r >= 80 ? "hi" : r >= 65 ? "mid" : "lo"; }

  function recCard(g, mode) {
    var card = el("div", "card");
    var cover = coverEl(g, "cover_big", 160, 226);
    if (mode === "series") {
      cover.appendChild(el("div", "match-badge series", "Series"));
    } else if (mode === "gems") {
      // discovery mode: show quality (rating) rather than a source-match %
      var rr = rating(g.total_rating);
      cover.appendChild(el("div", "match-badge " + ratingClass(rr ? +rr : null), rr ? "★ " + rr : "rare"));
    } else {
      var mi = g._match || matchInfo(g, sourceGame, mode);
      g._match = mi;
      cover.appendChild(el("div", "match-badge " + (mi.pct >= 75 ? "hi" : mi.pct >= 50 ? "mid" : "lo"), mi.pct + "% match"));
    }
    card.appendChild(cover);
    card.appendChild(el("div", "card-name", g.name));
    var sub = [];
    if (g.release_year) sub.push(String(g.release_year));
    var r = rating(g.total_rating); if (r) sub.push("★ " + r);
    if (mode === "gems" && typeof g.total_rating_count === "number") sub.push(g.total_rating_count + " reviews");
    else if (arr(g.genres).length) sub.push(arr(g.genres)[0]);
    card.appendChild(el("div", "card-sub", sub.join("  ·  ")));
    attachCardInteraction(card, g);
    return card;
  }

  function renderRecs(recs, mode) {
    var grid = $("#recs-grid");
    grid.innerHTML = "";

    // Same-series titles belong to SMART only (series is metadata). Looks-alike
    // stays purely visual and Hidden gems purely discovery - no series row there.
    var inSeries = {};
    if (mode === "smart" && currentSeries.length) {
      grid.appendChild(el("div", "grid-label", "More from this series"));
      currentSeries.forEach(function (g) { inSeries[g.id] = 1; grid.appendChild(recCard(g, "series")); });
      grid.appendChild(el("div", "grid-label", "More games like it"));
    }

    // Score & sort by the active mode's own signal, strictly high → low.
    if (mode !== "gems") {
      recs.forEach(function (g) { g._match = matchInfo(g, sourceGame, mode); });
      recs.sort(function (a, b) { return b._match.pct - a._match.pct; });
    } else {
      // Hidden gems show a ★ rating - order them by it, high → low.
      recs.sort(function (a, b) { return (parseFloat(b.total_rating) || 0) - (parseFloat(a.total_rating) || 0); });
    }
    recs.forEach(function (g) {
      if (inSeries[g.id]) return; // already shown above
      grid.appendChild(recCard(g, mode));
    });
  }

  // Tap = open detail (with why). Press & hold = peek screenshots.
  function attachCardInteraction(card, game) {
    var holdT = null, held = false;
    function startHold() {
      held = false;
      clearTimeout(holdT);
      holdT = setTimeout(function () { held = true; showPreview(game); }, 320);
    }
    function endHold() { clearTimeout(holdT); if (held) hidePreview(); }
    card.addEventListener("pointerdown", startHold);
    card.addEventListener("pointerup", endHold);
    card.addEventListener("pointerleave", endHold);
    card.addEventListener("pointercancel", endHold);
    card.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    card.addEventListener("click", function () {
      if (held) { held = false; return; } // the hold already showed a preview
      openDetail(game, sourceGame, currentMode);
    });
    // Desktop hover convenience
    card.addEventListener("mouseenter", function () { showPreview(game); });
    card.addEventListener("mouseleave", function () { hidePreview(); });
  }

  var previewTimer = null;
  function showPreview(game) {
    var shots = arr(game.screenshot_ids);
    if (!shots.length) return;
    var box = $("#preview");
    $("#preview-name").textContent = game.name;
    var holder = $("#preview-shots");
    holder.innerHTML = "";
    shots.slice(0, 4).forEach(function (sid) {
      var im = new Image();
      im.alt = ""; im.decoding = "async";
      im.src = shot(sid, "screenshot_med");
      holder.appendChild(im);
    });
    box.hidden = false;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(hidePreview, 2500); // safety auto-dismiss
  }
  function hidePreview() { clearTimeout(previewTimer); var box = $("#preview"); if (box) box.hidden = true; }

  // ============================================================ LIGHTBOX
  var lbShots = [], lbIndex = 0, lbName = "";
  function openLightbox(shots, index, name) {
    lbShots = shots; lbIndex = index; lbName = name || "";
    $("#lightbox").hidden = false;
    renderLightbox();
  }
  function renderLightbox() {
    var im = $("#lb-img");
    im.classList.remove("ready");
    im.onload = function () { im.classList.add("ready"); };
    im.src = shot(lbShots[lbIndex], "1080p"); // full quality
    im.alt = lbName + " screenshot " + (lbIndex + 1);
    $("#lb-counter").textContent = (lbIndex + 1) + " / " + lbShots.length;
  }
  function lbStep(d) { lbIndex = (lbIndex + d + lbShots.length) % lbShots.length; renderLightbox(); }
  function closeLightbox() { $("#lightbox").hidden = true; }

  function initLightbox() {
    $("#lb-close").addEventListener("click", closeLightbox);
    $("#lb-prev").addEventListener("click", function (e) { e.stopPropagation(); lbStep(-1); });
    $("#lb-next").addEventListener("click", function (e) { e.stopPropagation(); lbStep(1); });
    $("#lightbox").addEventListener("click", function (e) { if (e.target.id === "lightbox") closeLightbox(); });
    var x0 = null, lb = $("#lightbox");
    lb.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
    lb.addEventListener("touchend", function (e) {
      if (x0 == null) return;
      var dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 40) lbStep(dx < 0 ? 1 : -1);
      x0 = null;
    });
  }

  // ============================================================ SHARE
  function shareText() {
    if (!sourceGame) return "";
    var lines = ["Because I love " + sourceGame.name + ", I should play:"];
    currentRecs.forEach(function (g, i) {
      var b = (i + 1) + ". " + g.name;
      if (g.release_year) b += " (" + g.release_year + ")";
      var r = rating(g.total_rating); if (r) b += " - ★ " + r + "/100";
      lines.push(b);
    });
    lines.push(""); lines.push("via PlayStation Game Recommender");
    return lines.join("\n");
  }
  function doShare() {
    var text = shareText(); if (!text) return;
    if (navigator.share) navigator.share({ title: "Game recommendations", text: text }).catch(function () {});
    else if (navigator.clipboard) navigator.clipboard.writeText(text).then(function () { toast("Copied to clipboard!"); });
    else toast("Sharing not supported.");
  }

  // ============================================================ PHOTO SEARCH
  // Fully on-device and free: the photo is embedded in the browser with the
  // open-source CLIP model (transformers.js, Xenova/clip-vit-base-patch32, q8)
  // - the SAME model that embedded every game's screenshots into game_clip_oss.
  // The resulting 512-d vector is matched by match_games_by_clip_oss (pgvector).
  // The model (~45 MB) downloads once and is then cached by the browser; the
  // photo itself never leaves the device. No server embedding, no API key.
  var CLIP_MODEL = "Xenova/clip-vit-base-patch32";
  var CLIP_LIB = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.5";
  var _embedder = null, _embedderPromise = null;

  function loadEmbedder() {
    if (_embedder) return Promise.resolve(_embedder);
    if (_embedderPromise) return _embedderPromise;
    _embedderPromise = import(CLIP_LIB).then(function (T) {
      T.env.allowLocalModels = false;
      // GitHub Pages isn't cross-origin-isolated, so multi-threaded WASM and
      // SharedArrayBuffer aren't available - pin to single-threaded WASM so
      // onnxruntime-web runs reliably on iOS Safari.
      try { T.env.backends.onnx.wasm.numThreads = 1; } catch (e) {}
      return Promise.all([
        T.AutoProcessor.from_pretrained(CLIP_MODEL),
        T.CLIPVisionModelWithProjection.from_pretrained(CLIP_MODEL, { dtype: "q8" }),
      ]).then(function (p) { _embedder = { T: T, processor: p[0], model: p[1] }; return _embedder; });
    });
    _embedderPromise.catch(function () { _embedderPromise = null; }); // allow a retry after failure
    return _embedderPromise;
  }

  // downscale to a small JPEG Blob first - keeps decoding light on phones and
  // the model resizes to 224 anyway
  function downscaleToBlob(file, max) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var im = new Image();
      im.onload = function () {
        var w = im.naturalWidth, h = im.naturalHeight, scale = Math.min(1, max / Math.max(w, h));
        var c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(w * scale));
        c.height = Math.max(1, Math.round(h * scale));
        c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        if (c.toBlob) c.toBlob(function (b) { resolve(b || file); }, "image/jpeg", 0.9);
        else resolve(file);
      };
      im.onerror = function () { URL.revokeObjectURL(url); reject(new Error("Couldn't read that image.")); };
      im.src = url;
    });
  }

  // embed a Blob/File into a unit-length 512-d vector (cosine-ready)
  function embedPhoto(emb, blob) {
    return emb.T.RawImage.fromBlob(blob)
      .then(function (image) { return emb.processor(image); })
      .then(function (inputs) { return emb.model(inputs); })
      .then(function (out) {
        var v = out.image_embeds.tolist()[0], s = 0, i;
        for (i = 0; i < v.length; i++) s += v[i] * v[i];
        s = Math.sqrt(s) || 1;
        for (i = 0; i < v.length; i++) v[i] = v[i] / s;
        return v;
      });
  }

  function handlePhoto(file) {
    if (!file) return;
    if (!_embedder) toast("Preparing visual search… first run downloads a small model (~45 MB)");
    showSpinner(true);
    loadEmbedder()
      .then(function (emb) {
        return downscaleToBlob(file, 512).then(function (blob) { return embedPhoto(emb, blob); });
      })
      .then(function (v) { return rpc("match_games_by_clip_oss", { query: JSON.stringify(v), lim: REC_COUNT }); })
      .then(function (games) {
        showSpinner(false);
        if (!games || !games.length) { toast("No close visual matches found."); return; }
        openPhotoResults(games);
      })
      .catch(function (err) {
        showSpinner(false);
        console.error("photo search:", err);
        toast("Photo search error: " + (err && err.message ? err.message : String(err)));
      });
  }

  function openPhotoResults(games) {
    sourceGame = null;
    currentVisScores = {};
    currentSeries = [];
    renderSourceBar(null, "Games that look like<br><b>your photo</b>");
    var seg = $("#rec-mode"); if (seg) seg.hidden = true;
    var subEl = document.querySelector(".recs-sub"); if (subEl) subEl.hidden = true;
    $("#recs-note").hidden = true;
    var grid = $("#recs-grid"); grid.innerHTML = "";
    // highest-rated visual matches first, and show the rating
    games = games.slice().sort(function (a, b) { return (parseFloat(b.total_rating) || 0) - (parseFloat(a.total_rating) || 0); });
    games.forEach(function (g) {
      var card = el("div", "card");
      var cover = coverEl(g, "cover_big", 160, 226);
      var rr = rating(g.total_rating);
      cover.appendChild(el("div", "match-badge " + ratingClass(rr ? +rr : null), rr ? "★ " + rr : "-"));
      card.appendChild(cover);
      card.appendChild(el("div", "card-name", g.name));
      var meta = [];
      if (g.release_year) meta.push(String(g.release_year));
      if (arr(g.genres).length) meta.push(arr(g.genres)[0]);
      card.appendChild(el("div", "card-sub", meta.join("  ·  ")));
      attachCardInteraction(card, g);
      grid.appendChild(card);
    });
    push("recs");
  }

  // ============================================================ HOME DEMO
  // A "how it works" gallery at the bottom of home, built from REAL cover art:
  // because you loved God of War → its actual top matches. Tapping it runs the
  // real recommendation flow for God of War.
  function buildHomeDemo() {
    var host = $("#home-demo");
    if (!host) return;
    var GOW = { id: 19560, name: "God of War", cover_id: "cobkt6" };
    var matches = [
      { id: 75235, name: "Ghost of Tsushima", cover_id: "co2crj", pct: 96 },
      { id: 112875, name: "God of War Ragnarök", cover_id: "coba3d", pct: 94 },
      { id: 119133, name: "Elden Ring", cover_id: "co4jni", pct: 91 },
      { id: 11156, name: "Horizon Zero Dawn", cover_id: "co2una", pct: 90 },
      { id: 25076, name: "Red Dead Redemption 2", cover_id: "co1q1f", pct: 88 },
    ];
    host.innerHTML = "";
    host.appendChild(el("div", "howto-h", "SEE IT IN ACTION"));

    var card = el("button", "demo"); card.type = "button";
    var top = el("div", "demo-top");
    var src = coverEl(GOW, "cover_small", 90, 128); src.classList.add("demo-src");
    top.appendChild(src);
    var because = el("div", "demo-because");
    because.innerHTML = "Because you loved <b>God of War</b><span>Tap to see real matches →</span>";
    top.appendChild(because);
    card.appendChild(top);

    var row = el("div", "demo-row");
    matches.forEach(function (m) {
      var cell = el("div", "demo-cell");
      var cv = coverEl(m, "cover_small", 90, 128);
      cv.appendChild(el("div", "match-badge " + (m.pct >= 75 ? "hi" : "mid"), m.pct + "%"));
      cell.appendChild(cv);
      row.appendChild(cell);
    });
    card.appendChild(row);
    card.addEventListener("click", function () { openPick(GOW.id); });
    host.appendChild(card);
    host.hidden = false;
  }

  // ============================================================ MY LIST (□)
  function openSavedList() {
    var saved = getSaved();
    sourceGame = null; currentVisScores = {}; currentSeries = [];
    renderSourceBar(null, "<b>My List</b><br>" + saved.length + " saved game" + (saved.length === 1 ? "" : "s"));
    var seg = $("#rec-mode"); if (seg) seg.hidden = true;
    var subEl = document.querySelector(".recs-sub"); if (subEl) subEl.hidden = true;
    var grid = $("#recs-grid"); grid.innerHTML = "";
    var note = $("#recs-note");
    if (!saved.length) {
      note.hidden = false;
      note.innerHTML = "Your list is empty. Open any game and tap <b>□ Save</b> to add it here.";
      push("recs"); return;
    }
    note.hidden = true;
    saved = saved.slice().sort(function (a, b) { return (parseFloat(b.total_rating) || 0) - (parseFloat(a.total_rating) || 0); });
    saved.forEach(function (g) {
      var card = el("div", "card");
      var cover = coverEl(g, "cover_big", 160, 226);
      var rr = rating(g.total_rating);
      cover.appendChild(el("div", "match-badge " + ratingClass(rr ? +rr : null), rr ? "★ " + rr : "-"));
      card.appendChild(cover);
      card.appendChild(el("div", "card-name", g.name));
      var meta = [];
      if (g.release_year) meta.push(String(g.release_year));
      if (arr(g.genres).length) meta.push(arr(g.genres)[0]);
      card.appendChild(el("div", "card-sub", meta.join("  ·  ")));
      card.addEventListener("click", function () { openPick(g.id); });
      grid.appendChild(card);
    });
    push("recs");
  }

  // ============================================================ INIT
  function init() {
    if (!URL_BASE || !KEY) { alert("Missing backend config (config.js)."); return; }
    initHome();
    initLightbox();
    document.querySelectorAll("[data-nav]").forEach(function (b) {
      b.addEventListener("click", b.getAttribute("data-nav") === "home" ? goHome : back);
    });
    document.querySelectorAll("#rec-mode .seg").forEach(function (b) {
      b.addEventListener("click", function () {
        var mode = b.getAttribute("data-mode");
        if (mode === currentMode) return;
        setActiveSeg(mode);
        loadMode(mode);
      });
    });
    var s = $("#share-btn"); if (s) s.addEventListener("click", doShare);
    var ml = $("#mylist-btn"); if (ml) ml.addEventListener("click", openSavedList);
    buildHomeDemo();

    // the press-and-hold preview must never get stuck on screen
    document.addEventListener("pointerup", hidePreview, true);
    document.addEventListener("pointercancel", hidePreview, true);
    document.addEventListener("touchend", hidePreview, true);
    var pv = $("#preview"); if (pv) pv.addEventListener("click", hidePreview);

    show("home");
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", function () { navigator.serviceWorker.register("sw.js").catch(function () {}); });
    }
  }

  // test hooks
  window.__app = {
    openPick: openPick, openDetail: openDetail, openRecs: openRecs,
    shareText: shareText, whyPanel: whyPanel, openLightbox: openLightbox,
    openPhotoResults: openPhotoResults, matchInfo: matchInfo,
    setConfig: function (c) { URL_BASE = c.SUPABASE_URL; KEY = c.SUPABASE_KEY; },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

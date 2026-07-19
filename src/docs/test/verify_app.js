/*
 * Headless verification of the PWA. Loads the real index.html in jsdom, stubs
 * every Supabase call with the shape the live API returns, then drives the
 * UI as a user would and asserts each feature renders. Kept intentionally
 * narrow - it protects against selector/wiring rot; feature-quality is
 * measured by the eval/ harness against the real backend.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const DIR = path.join(__dirname, "..");
let html = fs.readFileSync(path.join(DIR, "index.html"), "utf8");
const configJs = fs.readFileSync(path.join(DIR, "config.js"), "utf8");
const appJs = fs.readFileSync(path.join(DIR, "app.js"), "utf8");
html = html
  .replace('<script src="config.js"></script>', "<script>" + configJs + "</script>")
  .replace('<script src="app.js"></script>', "<script>" + appJs + "</script>");

// ----- fixtures shaped like real backend responses -----
const STATS = [{ games: 7085, min_year: 1980, max_year: 2028, upcoming: 315, photo_searchable: 6594 }];

const SEARCH = [
  { id: 19560, name: "God of War", release_year: 2018, total_rating: "94.1", cover_id: "cobkt6" },
  { id: 112875, name: "God of War Ragnarok", release_year: 2022, total_rating: "92.8", cover_id: "coba3d" },
  { id: 389443, name: "God of War Sons of Sparta", release_year: 2026, total_rating: "72.6", cover_id: "cobigb" },
];

const DETAIL = {
  id: 19560, name: "God of War", release_year: 2018, total_rating: "94.1", cover_id: "cobkt6",
  summary: "God of War is the sequel to God of War III, focusing on Norse mythology.",
  genres: ["Role-playing (RPG)", "Hack and slash/Beat 'em up", "Adventure"],
  themes: ["Action", "Fantasy", "Historical"],
  developers: ["SIE Santa Monica Studio"], publishers: ["Sony Interactive Entertainment"],
  game_modes: ["Single player"], similar_games: [112875, 26192, 19565],
  franchises: ["God of War"], collections: ["God of War"],
  screenshot_ids: ["shot_a", "shot_b", "shot_c"], artwork_ids: [],
};

function mkRec(i, id, name, year, rt, genres) {
  return {
    id, name, release_year: year, total_rating: rt, cover_id: "co" + id,
    genres, themes: ["Action"], developers: i === 0 ? ["SIE Santa Monica Studio"] : ["Studio " + i],
    game_modes: ["Single player"], similar_games: [], franchises: [], collections: [],
    screenshot_ids: ["s" + id + "a", "s" + id + "b"], artwork_ids: [],
  };
}

const RECS = [
  mkRec(0, 112875, "God of War Ragnarok", 2022, "92.8", ["Role-playing (RPG)", "Adventure"]),
  mkRec(1, 105049, "Remnant: From the Ashes", 2019, "76.3", ["Shooter"]),
  mkRec(2, 76882, "Sekiro: Shadows Die Twice", 2019, "89.8", ["Adventure"]),
  mkRec(3, 112874, "Horizon Forbidden West", 2022, "88.7", ["Adventure"]),
  mkRec(4, 19565, "Marvel's Spider-Man", 2018, "88.3", ["Adventure"]),
  mkRec(5, 11156, "Horizon Zero Dawn", 2017, "88.1", ["Adventure"]),
  mkRec(6, 26192, "The Last of Us Part II", 2020, "92.6", ["Adventure"]),
  mkRec(7, 12571, "Nioh", 2017, "83.5", ["Role-playing (RPG)"]),
  mkRec(8, 55199, "Dragon: Marked for Death", 2019, "73.5", ["Adventure"]),
  mkRec(9, 7331, "Bloodborne", 2015, "91.2", ["Role-playing (RPG)"]),
  mkRec(10, 19564, "God of War III Remastered", 2015, "80.0", ["Adventure"]),
  mkRec(11, 113114, "Ghost of Tsushima", 2020, "89.4", ["Adventure"]),
];

const MEDIA = [
  { source: "steam", image_url: "https://steamuserimages-a.akamaihd.net/ugc/aaa.jpg",
    thumb_url: "https://steamuserimages-a.akamaihd.net/ugc/aaa.jpg",
    source_url: "https://steamcommunity.com/sharedfiles/filedetails/?id=1", caption: null },
  { source: "reddit", image_url: "https://i.redd.it/bbb.jpg", thumb_url: null,
    author: "u/gamer", source_url: "https://www.reddit.com/r/PS5/x", caption: "my shot" },
];

const VISN = [{
  neighbor_ids: RECS.map((r) => r.id),
  scores: RECS.map((_, i) => Number((0.95 - i * 0.03).toFixed(4))),
}];

const calls = [];
function fakeFetch(url) {
  calls.push(url);
  let data = [];
  if (url.includes("/rpc/get_stats")) data = STATS;
  else if (url.includes("/rpc/search_games")) data = SEARCH;
  else if (url.includes("/rpc/get_visual_recommendations")) data = RECS.slice(0, 12);
  else if (url.includes("/rpc/get_recommendations")) data = RECS;
  else if (url.includes("/rpc/get_hidden_gems")) data = RECS;
  else if (url.includes("/rpc/match_games_by_clip_oss")) data = RECS.slice(0, 12);
  else if (url.includes("/rest/v1/visual_neighbors")) data = VISN;
  else if (url.includes("/rest/v1/user_media")) data = MEDIA;
  else if (url.includes("/rest/v1/games?id=eq.19560")) data = [DETAIL];
  return Promise.resolve({
    ok: true, status: 200,
    headers: { get: () => "0-0/7085" },
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

const fail = (m) => { console.error("FAIL: " + m); process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "https://example.com/",
    beforeParse(window) {
      window.fetch = fakeFetch;
      window.scrollTo = () => {};
      if (!window.PointerEvent) window.PointerEvent = window.Event;
    },
  });
  const { window } = dom;
  const doc = window.document;
  await sleep(60);
  if (!window.__app) fail("app did not initialise");

  // ---- 1. autocomplete ----
  const input = doc.querySelector("#search-input");
  input.value = "god of war";
  input.dispatchEvent(new window.Event("input"));
  await sleep(300);
  const items = doc.querySelectorAll("#suggest .suggest-item");
  if (items.length !== 3) fail("autocomplete should show 3 suggestions, got " + items.length);
  if (!doc.querySelector("#suggest").textContent.includes("God of War Ragnarok"))
    fail("suggestion text missing");
  console.log("  OK  autocomplete shows live suggestions as you type");

  // ---- 2. detail with gallery + player captures ----
  items[0].dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(60);
  if (!doc.querySelector("#view-detail.active")) fail("did not open detail");
  const dbody = doc.querySelector("#detail-body");
  if (!dbody.textContent.includes("God of War")) fail("detail title missing");
  if (!dbody.textContent.includes("SIE Santa Monica Studio")) fail("developer missing");
  const shots = dbody.querySelectorAll(".gallery .shot:not(.pc-shot)");
  if (shots.length !== 3) fail("gallery should show 3 screenshots, got " + shots.length);
  if (dbody.querySelector(".why")) fail("source pick should NOT show a why-panel");
  const pcs = dbody.querySelectorAll(".pc-shot");
  if (pcs.length !== 2) fail("player captures should show 2 items, got " + pcs.length);
  if (pcs[0].getAttribute("href") !== "https://steamcommunity.com/sharedfiles/filedetails/?id=1")
    fail("player capture should link to its source");
  console.log("  OK  detail renders gallery + player-captures section");

  // ---- 3. recommendations (default = visual look-alike) + match badges ----
  const cta = [...dbody.querySelectorAll("button")].find((b) => /recommendation/i.test(b.textContent));
  if (!cta) fail("recommendations button missing");
  cta.dispatchEvent(new window.Event("click"));
  await sleep(100);
  if (!doc.querySelector("#view-recs.active")) fail("did not open recs");
  const j0 = calls.join("\n");
  if (!j0.includes("/rest/v1/visual_neighbors")) fail("did not fetch visual scores");
  if (!j0.includes("/rpc/get_visual_recommendations")) fail("default mode should be visual look-alike");
  const cards = doc.querySelectorAll("#recs-grid .card");
  if (cards.length !== 12) fail("expected 12 recs, got " + cards.length);
  const badges = doc.querySelectorAll("#recs-grid .match-badge");
  if (badges.length < 10) fail("most cards should carry a match badge, got " + badges.length);
  if (!/%\s*match/i.test(badges[0].textContent)) fail("badge should read 'NN% match', got " + badges[0].textContent);
  console.log("  OK  visual recommendations: 12 cards with match badges");

  // ---- 4. tap a card -> detail with score breakdown ----
  cards[0].dispatchEvent(new window.Event("click"));
  await sleep(40);
  const why = doc.querySelector("#detail-body .why");
  if (!why) fail("recommended detail must show a why-panel");
  const sb = why.querySelector(".score-block");
  if (!sb) fail("why-panel must show the score breakdown block");
  if (!/Gameplay look-alike/i.test(sb.textContent))
    fail("visual mode score block should list 'Gameplay look-alike' row");
  console.log("  OK  recommendation detail shows the visual score breakdown");

  // ---- 5. Smart toggle ----
  doc.querySelector("#view-detail [data-nav=back]").dispatchEvent(new window.Event("click"));
  await sleep(30);
  const smartSeg = [...doc.querySelectorAll("#rec-mode .seg")].find((b) => b.dataset.mode === "smart");
  if (!smartSeg) fail("smart toggle missing");
  smartSeg.dispatchEvent(new window.Event("click"));
  await sleep(80);
  if (!calls.join("\n").includes("/rpc/get_recommendations")) fail("smart RPC never called");
  if (doc.querySelectorAll("#recs-grid .card").length < 12) fail("smart mode should render >=12 cards");
  console.log("  OK  Smart toggle calls get_recommendations");

  // ---- 6. Hidden gems tab ----
  const gemsSeg = [...doc.querySelectorAll("#rec-mode .seg")].find((b) => b.dataset.mode === "gems");
  if (!gemsSeg) fail("Hidden gems tab missing");
  gemsSeg.dispatchEvent(new window.Event("click"));
  await sleep(80);
  if (!calls.join("\n").includes("/rpc/get_hidden_gems")) fail("gems RPC never called");
  if (doc.querySelectorAll("#recs-grid .card").length !== 12) fail("gems should render 12 cards");
  if (!doc.querySelector("#view-recs [data-nav=home]")) fail("Home button missing on recs screen");
  console.log("  OK  Hidden gems tab calls get_hidden_gems; Home button present");

  // ---- 7. photo-search entry + results renderer ----
  if (!doc.querySelector("#photo-btn")) fail("photo-search button missing");
  window.__app.openPhotoResults(RECS.slice(0, 12));
  await sleep(30);
  if (doc.querySelectorAll("#recs-grid .card").length !== 12) fail("photo results should render 12 cards");
  if (!/look like|your photo/i.test(doc.querySelector("#rec-source").textContent))
    fail("photo source bar wrong");
  console.log("  OK  photo search: entry present + results screen renders");

  // ---- 8. lightbox at t_1080p ----
  doc.querySelector("#view-recs [data-nav=back], #view-detail [data-nav=back]")
    ?.dispatchEvent(new window.Event("click"));
  await sleep(20);
  window.__app.openLightbox(DETAIL.screenshot_ids, 0, DETAIL.name);
  await sleep(10);
  if (doc.querySelector("#lightbox").hidden) fail("lightbox did not open");
  if (!/t_1080p/.test(doc.querySelector("#lb-img").src)) fail("lightbox should request t_1080p");
  console.log("  OK  gallery lightbox opens full-quality (1080p)");

  // ---- 9. endpoint coverage ----
  const j = calls.join("\n");
  const required = [
    "/rpc/get_stats", "/rpc/search_games", "/rest/v1/games?id=eq.19560",
    "/rpc/get_visual_recommendations", "/rpc/get_recommendations", "/rpc/get_hidden_gems",
    "/rest/v1/visual_neighbors", "/rest/v1/user_media",
  ];
  for (const e of required) if (!j.includes(e)) fail("never called " + e);
  console.log("  OK  called every expected Supabase endpoint");

  console.log("\nALL CHECKS PASSED");
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });

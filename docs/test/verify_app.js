/*
 * Headless verification for the PWA.
 *
 * Loads the real index.html in jsdom, stubs `fetch` with the SAME shape the
 * live Supabase API returns, then drives the UI as a user would and asserts
 * each new feature renders real data:
 *
 *   type "god of war" → autocomplete suggestions → pick → detail (gallery,
 *   about) → See recommendations (12 cards) → tap a card → detail shows the
 *   "Why we picked this" panel → lightbox opens a full-quality screenshot.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const DIR = path.join(__dirname, ".."); // the app folder (docs/)
let html = fs.readFileSync(path.join(DIR, "index.html"), "utf8");
const configJs = fs.readFileSync(path.join(DIR, "config.js"), "utf8");
const appJs = fs.readFileSync(path.join(DIR, "app.js"), "utf8");
html = html
  .replace('<script src="config.js"></script>', "<script>" + configJs + "</script>")
  .replace('<script src="app.js"></script>', "<script>" + appJs + "</script>");

// ---- real-shaped fixtures ----
const SEARCH = [
  { id: 19560, name: "God of War", release_year: 2018, total_rating: "94.1", cover_id: "cobkt6" },
  { id: 112875, name: "God of War Ragnarök", release_year: 2022, total_rating: "92.8", cover_id: "coba3d" },
  { id: 389443, name: "God of War Sons of Sparta", release_year: 2026, total_rating: "72.6", cover_id: "cobigb" },
];
const DETAIL = {
  id: 19560, name: "God of War", release_year: 2018, total_rating: "94.1", cover_id: "cobkt6",
  summary: "God of War is the sequel to God of War III, focusing on Norse mythology.",
  genres: ["Role-playing (RPG)", "Hack and slash/Beat 'em up", "Adventure"],
  themes: ["Action", "Fantasy", "Historical"],
  developers: ["SIE Santa Monica Studio"], publishers: ["Sony Interactive Entertainment"],
  game_modes: ["Single player"], similar_games: ["112875", "26192", "19565"],
  screenshot_ids: ["rm35ytrytuka9qkylqyk", "ywrkjcrbeemmb51flsfj", "qseegzssgetrybgbplrv"],
  artwork_ids: [],
};
function mkRec(i, id, name, year, rt, genres, similar) {
  return {
    id, name, release_year: year, total_rating: rt, cover_id: "co" + id,
    genres, themes: ["Action"], developers: i === 0 ? ["SIE Santa Monica Studio"] : ["Studio " + i],
    game_modes: ["Single player"], similar_games: [], screenshot_ids: ["shot" + id + "a", "shot" + id + "b"],
  };
}
const RECS = [
  mkRec(0, 112875, "God of War Ragnarök", 2022, "92.8", ["Role-playing (RPG)", "Adventure"]),
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
  { source: "steam", image_url: "https://steamuserimages-a.akamaihd.net/ugc/aaa.jpg", thumb_url: "https://steamuserimages-a.akamaihd.net/ugc/aaa.jpg", author: "Steam player", source_url: "https://steamcommunity.com/sharedfiles/filedetails/?id=1", caption: null },
  { source: "reddit", image_url: "https://i.redd.it/bbb.jpg", thumb_url: null, author: "u/gamer", source_url: "https://www.reddit.com/r/PS5/x", caption: "my best shot" },
];

// visual_neighbors row for the source (19560): cosine scores for the rec ids
const VISN = [{
  neighbor_ids: RECS.map((r) => r.id),
  scores: RECS.map((_, i) => Number((0.95 - i * 0.03).toFixed(4))),
}];

const calls = [];
function fakeFetch(url) {
  calls.push(url);
  let data = [];
  if (url.includes("/rpc/search_games")) data = SEARCH;
  else if (url.includes("/rpc/get_visual_recommendations")) data = RECS.slice(0, 12);
  else if (url.includes("/rpc/get_recommendations")) data = RECS;
  else if (url.includes("/rest/v1/visual_neighbors")) data = VISN;
  else if (url.includes("/rest/v1/user_media")) data = MEDIA;
  else if (url.includes("/rest/v1/games?id=eq.19560")) data = [DETAIL];
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data), text: () => Promise.resolve(JSON.stringify(data)) });
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
  await sleep(40);
  if (!window.__app) fail("app did not initialise");

  // ---- 1. autocomplete ----
  const input = doc.querySelector("#search-input");
  input.value = "god of war";
  input.dispatchEvent(new window.Event("input"));
  await sleep(300); // debounce + render
  const items = doc.querySelectorAll("#suggest .suggest-item");
  if (items.length !== 3) fail("autocomplete should show 3 suggestions, got " + items.length);
  if (!doc.querySelector("#suggest").textContent.includes("God of War Ragnarök")) fail("suggestion text missing");
  console.log("  ✓ autocomplete shows live suggestions as you type");

  // ---- 2. pick → detail with gallery ----
  items[0].dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(40);
  if (!doc.querySelector("#view-detail.active")) fail("did not open detail");
  const dbody = doc.querySelector("#detail-body");
  if (!dbody.textContent.includes("God of War")) fail("detail title missing");
  if (!dbody.textContent.includes("SIE Santa Monica Studio")) fail("developer missing");
  const shots = dbody.querySelectorAll(".gallery .shot:not(.pc-shot)");
  if (shots.length !== 3) fail("official gallery should show 3 screenshots, got " + shots.length);
  if (dbody.querySelector(".why")) fail("source pick should NOT show a why-panel");
  const pcs = dbody.querySelectorAll(".pc-shot");
  if (pcs.length !== 2) fail("player-captures should show 2 items, got " + pcs.length);
  if (!/Player captures/.test(dbody.textContent)) fail("player-captures section header missing");
  if (pcs[0].getAttribute("href") !== "https://steamcommunity.com/sharedfiles/filedetails/?id=1")
    fail("player capture should link to its source");
  console.log("  ✓ detail renders gallery + 'Player captures' (Steam/Reddit links) section");

  // ---- 3. recommendations (default = visual look-alike) + match badges ----
  const cta = [...dbody.querySelectorAll("button")].find((b) => /recommendation/i.test(b.textContent));
  if (!cta) fail("recommendations button missing");
  cta.dispatchEvent(new window.Event("click"));
  await sleep(80); // fetchVisScores → loadMode(visual)
  if (!doc.querySelector("#view-recs.active")) fail("did not open recs");
  if (!calls.join("\n").includes("/rest/v1/visual_neighbors")) fail("did not fetch visual scores");
  if (!calls.join("\n").includes("/rpc/get_visual_recommendations")) fail("default mode should be visual look-alike");
  const cards = doc.querySelectorAll("#recs-grid .card");
  if (cards.length !== 12) fail("expected 12 recommendations, got " + cards.length);
  const badges = doc.querySelectorAll("#recs-grid .match-badge");
  if (badges.length !== 12) fail("every card needs a match badge, got " + badges.length);
  if (!/%\s*match/i.test(badges[0].textContent)) fail("badge should read 'NN% match', got " + badges[0].textContent);
  console.log("  ✓ 12 recommendations, each with a '% match' badge (visual default)");

  // ---- 4. tap a card → detail shows the score breakdown ----
  cards[0].dispatchEvent(new window.Event("click"));
  await sleep(40);
  const why = doc.querySelector("#detail-body .why");
  if (!why) fail("recommended game's detail must show a why-panel");
  const sb = why.querySelector(".score-block");
  if (!sb) fail("why-panel must show the score breakdown block");
  if (!/% match|match with/i.test(sb.textContent)) fail("score block should show the % match");
  if (!/Gameplay look-alike/i.test(sb.textContent)) fail("score block should list gameplay look-alike as a factor");
  if (!/Shared genres/i.test(sb.textContent)) fail("score block should list shared genres");
  if (!/Release era/i.test(sb.textContent)) fail("score block should list release-year closeness");
  console.log("  ✓ recommendation detail shows a clear match-score breakdown (visual + genre + year)");

  // ---- 4b. Smart match toggle still works ----
  doc.querySelector("#view-detail .btn-back").dispatchEvent(new window.Event("click"));
  await sleep(20);
  const smartSeg = [...doc.querySelectorAll("#rec-mode .seg")].find((b) => b.dataset.mode === "smart");
  if (!smartSeg) fail("smart toggle missing");
  smartSeg.dispatchEvent(new window.Event("click"));
  await sleep(40);
  if (!calls.join("\n").includes("/rpc/get_recommendations")) fail("smart endpoint never called");
  if (doc.querySelectorAll("#recs-grid .card").length !== 12) fail("smart mode should render 12 cards");
  console.log("  ✓ 'Smart match' toggle calls get_recommendations and renders cards");

  // ---- 4c. photo-search results screen ----
  if (!doc.querySelector("#photo-btn")) fail("'Search by photo' button missing");
  window.__app.openPhotoResults(RECS.slice(0, 12));
  await sleep(20);
  if (doc.querySelectorAll("#recs-grid .card").length !== 12) fail("photo results should render 12 cards");
  if (!/look like|your photo/i.test(doc.querySelector("#rec-source").textContent)) fail("photo source bar wrong");
  if (!doc.querySelector("#rec-mode").hidden) fail("mode toggle should be hidden in photo mode");
  console.log("  ✓ search-by-photo results screen renders (button + grid + hidden toggle)");
  // return to recs for the rest of the checks
  doc.querySelector("#view-detail .btn-back").dispatchEvent(new window.Event("click"));
  await sleep(20);

  // ---- 5. lightbox ----
  window.__app.openLightbox(DETAIL.screenshot_ids, 0, DETAIL.name);
  await sleep(10);
  if (doc.querySelector("#lightbox").hidden) fail("lightbox did not open");
  const lbSrc = doc.querySelector("#lb-img").src;
  if (!/t_1080p/.test(lbSrc)) fail("lightbox should request full-quality (t_1080p) image, got " + lbSrc);
  console.log("  ✓ gallery lightbox opens full-quality (1080p) screenshots");

  // ---- 6. endpoints ----
  const j = calls.join("\n");
  ["/rpc/search_games", "/rest/v1/games?id=eq.19560", "/rpc/get_recommendations"].forEach((e) => {
    if (!j.includes(e)) fail("never called " + e);
  });
  console.log("  ✓ called the real Supabase endpoints");

  console.log("\nALL CHECKS PASSED — autocomplete, gallery, 12 recs, why-panel & lightbox all work.");
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });

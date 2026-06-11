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

const calls = [];
function fakeFetch(url) {
  calls.push(url);
  let data = [];
  if (url.includes("/rpc/search_games")) data = SEARCH;
  else if (url.includes("/rpc/get_visual_recommendations")) data = RECS.slice(0, 12);
  else if (url.includes("/rpc/get_recommendations")) data = RECS;
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
  const shots = dbody.querySelectorAll(".gallery .shot");
  if (shots.length !== 3) fail("gallery should show 3 screenshots, got " + shots.length);
  if (dbody.querySelector(".why")) fail("source pick should NOT show a why-panel");
  console.log("  ✓ detail renders info + screenshot gallery (no why-panel for the picked game)");

  // ---- 3. recommendations (>=10) ----
  const cta = [...dbody.querySelectorAll("button")].find((b) => /recommendation/i.test(b.textContent));
  if (!cta) fail("recommendations button missing");
  cta.dispatchEvent(new window.Event("click"));
  await sleep(40);
  if (!doc.querySelector("#view-recs.active")) fail("did not open recs");
  const cards = doc.querySelectorAll("#recs-grid .card");
  if (cards.length < 10) fail("need at least 10 recommendations, got " + cards.length);
  if (cards.length !== 12) fail("expected 12 recommendations, got " + cards.length);
  console.log("  ✓ shows " + cards.length + " recommendations (>= 10)");

  // ---- 4. tap a card → detail with WHY panel ----
  cards[0].dispatchEvent(new window.Event("click"));
  await sleep(40);
  const why = doc.querySelector("#detail-body .why");
  if (!why) fail("recommended game's detail must show a why-panel");
  const wt = why.textContent;
  if (!/Why we picked this/i.test(wt)) fail("why-panel heading missing");
  if (!/directly similar/i.test(wt)) fail("why-panel should note the direct-similarity match");
  if (!/SIE Santa Monica Studio/.test(wt)) fail("why-panel should note shared studio");
  if (!/\+1000/.test(wt)) fail("why-panel should explain the scoring weights");
  console.log("  ✓ recommended game shows 'Why we picked this' with real, specific reasons");

  // ---- 4b. visual "Looks alike" toggle ----
  // go back to the recommendations screen first
  doc.querySelector("#view-detail .btn-back").dispatchEvent(new window.Event("click"));
  await sleep(20);
  const visSeg = [...doc.querySelectorAll("#rec-mode .seg")].find((b) => b.dataset.mode === "visual");
  if (!visSeg) fail("visual toggle missing");
  visSeg.dispatchEvent(new window.Event("click"));
  await sleep(40);
  if (!calls.join("\n").includes("/rpc/get_visual_recommendations")) fail("visual endpoint never called");
  const visCards = doc.querySelectorAll("#recs-grid .card");
  if (visCards.length !== 12) fail("visual mode should render 12 cards, got " + visCards.length);
  console.log("  ✓ 'Looks alike' toggle calls get_visual_recommendations and renders cards");

  // tap a visual card → visual why-panel
  visCards[0].dispatchEvent(new window.Event("click"));
  await sleep(40);
  const vwhy = doc.querySelector("#detail-body .why");
  if (!vwhy) fail("visual recommendation should show a why-panel");
  if (!/looks like|visual/i.test(vwhy.textContent)) fail("visual why-panel should explain visual similarity");
  if (!/visual fingerprint|neural network/i.test(vwhy.textContent)) fail("visual why-panel should describe the CNN method");
  console.log("  ✓ visual recommendation shows the computer-vision 'why' explanation");
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

/*
 * Headless verification for the iPhone PWA.
 *
 * Loads the real index.html in jsdom, stubs `fetch` so it returns the SAME
 * payloads the live Supabase API returned for these calls (captured from the
 * production DB), then drives the UI exactly as a user would:
 *
 *    type "god of war" → Search → tap result → Detail → See recommendations
 *
 * and asserts that real game data renders into the DOM at each step.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const DIR = path.join(__dirname, ".."); // the app folder (docs/)
let html = fs.readFileSync(path.join(DIR, "index.html"), "utf8");
// Inline the external scripts so jsdom executes them (no real network/resources).
const configJs = fs.readFileSync(path.join(DIR, "config.js"), "utf8");
const appJs = fs.readFileSync(path.join(DIR, "app.js"), "utf8");
html = html
  .replace('<script src="config.js"></script>', "<script>" + configJs + "</script>")
  .replace('<script src="app.js"></script>', "<script>" + appJs + "</script>");

// ---- real fixtures captured from the live Supabase project ----------------
const SEARCH = [
  { id: 19560, name: "God of War", release_year: 2018, total_rating: "94.13552098711254", cover_id: "cobkt6" },
  { id: 112875, name: "God of War Ragnarök", release_year: 2022, total_rating: "92.83203418928693", cover_id: "coba3d" },
  { id: 389443, name: "God of War Sons of Sparta", release_year: 2026, total_rating: "72.61211686473702", cover_id: "cobigb" },
];
const DETAIL = {
  id: 19560, name: "God of War", release_year: 2018, total_rating: "94.13552098711254",
  cover_id: "cobkt6", summary: "God of War is the sequel to God of War III...",
  genres: ["Role-playing (RPG)", "Hack and slash/Beat 'em up", "Adventure"],
  themes: ["Action", "Fantasy", "Historical"],
  developers: ["SIE Santa Monica Studio"], publishers: ["Sony Interactive Entertainment"],
};
const RECS = [
  { id: 112875, name: "God of War Ragnarök", release_year: 2022, total_rating: "92.83", cover_id: "coba3d", genres: ["Adventure"] },
  { id: 105049, name: "Remnant: From the Ashes", release_year: 2019, total_rating: "76.38", cover_id: "co1m4w", genres: ["Shooter"] },
  { id: 76882, name: "Sekiro: Shadows Die Twice", release_year: 2019, total_rating: "89.89", cover_id: "co2a23", genres: ["Adventure"] },
  { id: 112874, name: "Horizon Forbidden West", release_year: 2022, total_rating: "88.77", cover_id: "co2gvu", genres: ["Adventure"] },
  { id: 19565, name: "Marvel's Spider-Man", release_year: 2018, total_rating: "88.36", cover_id: "co1r77", genres: ["Adventure"] },
  { id: 11156, name: "Horizon Zero Dawn", release_year: 2017, total_rating: "88.12", cover_id: "co2una", genres: ["Shooter"] },
  { id: 26192, name: "The Last of Us Part II", release_year: 2020, total_rating: "92.62", cover_id: "co5ziw", genres: ["Shooter"] },
  { id: 12571, name: "Nioh", release_year: 2017, total_rating: "83.53", cover_id: "co20xg", genres: ["Role-playing (RPG)"] },
  { id: 55199, name: "Dragon: Marked for Death", release_year: 2019, total_rating: "73.5", cover_id: "co9ihr", genres: ["Adventure"] },
];

const calls = [];
function fakeFetch(url, opts) {
  calls.push(url);
  let data;
  if (url.includes("/rpc/search_games")) data = SEARCH;
  else if (url.includes("/rpc/get_recommendations")) data = RECS;
  else if (url.includes("/rest/v1/games?id=eq.19560")) data = [DETAIL];
  else data = [];
  return Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

const fail = (m) => { console.error("FAIL: " + m); process.exit(1); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    resources: undefined,
    url: "https://example.com/ios-app/",
    beforeParse(window) {
      window.fetch = fakeFetch;
      window.scrollTo = () => {};
    },
  });
  const { window } = dom;
  const doc = window.document;

  // wait for app.js init
  await sleep(50);
  if (!window.__app) fail("app did not initialise (window.__app missing)");
  if (!doc.querySelector("#view-home.active")) fail("home view not shown on load");

  // ----- 1. search -----
  doc.querySelector("#search-input").value = "god of war";
  doc.querySelector("#search-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await sleep(50);

  const results = doc.querySelectorAll("#results .result");
  if (results.length !== 3) fail("expected 3 search results, got " + results.length);
  if (!doc.querySelector("#results").textContent.includes("God of War Ragnarök"))
    fail("search results missing real game name");
  if (!doc.body.textContent.includes("★ 94")) fail("rating not rendered (expected ★ 94)");
  console.log("  ✓ search rendered 3 real results with ratings");

  // ----- 2. detail (tap first result) -----
  results[0].dispatchEvent(new window.Event("click"));
  await sleep(50);
  if (!doc.querySelector("#view-detail.active")) fail("did not navigate to detail view");
  const detailTxt = doc.querySelector("#detail-body").textContent;
  if (!detailTxt.includes("God of War")) fail("detail title missing");
  if (!detailTxt.includes("SIE Santa Monica Studio")) fail("developer not rendered");
  if (!detailTxt.includes("Role-playing (RPG)")) fail("genre chip not rendered");
  if (!detailTxt.includes("sequel to God of War III")) fail("summary not rendered");
  console.log("  ✓ detail rendered title, developer, genre chips, summary");

  // ----- 3. recommendations -----
  const cta = [...doc.querySelectorAll("#detail-body button")].find((b) => /recommendation/i.test(b.textContent));
  if (!cta) fail("recommendations button not found");
  cta.dispatchEvent(new window.Event("click"));
  await sleep(50);
  if (!doc.querySelector("#view-recs.active")) fail("did not navigate to recommendations view");
  const cards = doc.querySelectorAll("#recs-grid .card");
  if (cards.length !== 9) fail("expected 9 recommendation cards, got " + cards.length);
  const recTxt = doc.querySelector("#recs-grid").textContent;
  ["Horizon Forbidden West", "Sekiro", "The Last of Us Part II", "Nioh"].forEach((n) => {
    if (!recTxt.includes(n)) fail("recommendation missing: " + n);
  });
  if (!doc.querySelector("#recs-heading").textContent.includes("Because you like"))
    fail("recommendations heading wrong");
  console.log("  ✓ recommendations rendered 9 real cards");

  // ----- 4. share text -----
  const share = window.__app.shareText();
  if (!share.includes("Because I love God of War") || !share.includes("Horizon Forbidden West"))
    fail("share text malformed");
  console.log("  ✓ share text built correctly");

  // ----- 5. correct API endpoints were called -----
  const joined = calls.join("\n");
  if (!joined.includes("/rpc/search_games")) fail("search_games endpoint never called");
  if (!joined.includes("/rest/v1/games?id=eq.19560")) fail("game detail endpoint never called");
  if (!joined.includes("/rpc/get_recommendations")) fail("get_recommendations endpoint never called");
  console.log("  ✓ called the real Supabase endpoints (search_games, games, get_recommendations)");

  console.log("\nALL CHECKS PASSED — full search → detail → recommendations flow works.");
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });

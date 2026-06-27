/*
 * Free, self-hosted catalog embedder for photo search.
 *
 * Embeds every PlayStation game's IGDB screenshots with the open-source CLIP
 * model Xenova/clip-vit-base-patch32 (512-d) using transformers.js on CPU, and
 * upserts the vectors into public.game_clip_oss. The browser embeds the query
 * photo with the EXACT same model, so query and catalog vectors live in the
 * same space - no Jina, no paid API, runs free on a GitHub Actions runner.
 *
 * Resumable: (game_id, shot_idx) pairs already in the table are skipped, so a
 * timed-out run just continues where it left off on the next dispatch.
 *
 * Env: SUPABASE_URL, SUPABASE_KEY (anon), SHOTS (default 3), LIMIT (0 = all),
 *      SELFCHECK (1 = after embedding, re-embed a few stored shots and confirm
 *      match_games_by_clip_oss returns their own game).
 */
import { AutoProcessor, CLIPVisionModelWithProjection, RawImage, env } from "@huggingface/transformers";

const URL = process.env.SUPABASE_URL.replace(/\/$/, "");
const KEY = process.env.SUPABASE_KEY;
const SHOTS = parseInt(process.env.SHOTS || "3", 10);
const LIMIT = parseInt(process.env.LIMIT || "0", 10);
const SELFCHECK = process.env.SELFCHECK === "1";
const MODEL = "Xenova/clip-vit-base-patch32";
const IMG = (id) => `https://images.igdb.com/igdb/image/upload/t_screenshot_med/${id}.jpg`;
const REST = `${URL}/rest/v1`;
const H = { apikey: KEY, Authorization: `Bearer ${KEY}` };

env.allowLocalModels = false; // always pull the canonical hub weights

const log = (...a) => console.log(...a);

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

async function fetchGames() {
  const out = [];
  for (let off = 0; ; off += 1000) {
    const rows = await getJSON(
      `${REST}/games?select=id,screenshot_ids&order=id.asc&limit=1000&offset=${off}`, { headers: H });
    out.push(...rows);
    if (rows.length < 1000) break;
  }
  const withShots = out.filter((g) => Array.isArray(g.screenshot_ids) && g.screenshot_ids.length);
  return LIMIT ? withShots.slice(0, LIMIT) : withShots;
}

async function fetchDone() {
  const done = new Set();
  for (let off = 0; ; off += 1000) {
    const rows = await getJSON(
      `${REST}/game_clip_oss?select=game_id,shot_idx&order=id.asc&limit=1000&offset=${off}`, { headers: H });
    for (const r of rows) done.add(`${r.game_id}:${r.shot_idx}`);
    if (rows.length < 1000) break;
  }
  return done;
}

function l2norm(v) {
  let s = 0;
  for (const x of v) s += x * x;
  s = Math.sqrt(s) || 1;
  return v.map((x) => x / s);
}

async function insertBatch(rows) {
  if (!rows.length) return;
  const r = await fetch(`${REST}/game_clip_oss?on_conflict=game_id,shot_idx`, {
    method: "POST",
    headers: { ...H, "Content-Type": "application/json", Prefer: "resolution=ignore-duplicates,return=minimal" },
    body: JSON.stringify(rows),
  });
  if (!r.ok) throw new Error(`insert ${r.status} ${await r.text()}`);
}

async function main() {
  log(`Loading ${MODEL} ...`);
  const processor = await AutoProcessor.from_pretrained(MODEL);
  // q8: the browser loads this exact quantized model (~45 MB), so catalog and
  // query vectors stay in the same space. Keep CI and browser dtype identical.
  const model = await CLIPVisionModelWithProjection.from_pretrained(MODEL, { dtype: "q8" });

  const embed = async (id) => {
    const image = await RawImage.read(IMG(id)); // fetch + decode
    const inputs = await processor(image);
    const { image_embeds } = await model(inputs);
    return l2norm(image_embeds.tolist()[0]);
  };

  const games = await fetchGames();
  const done = await fetchDone();
  log(`Games with screenshots: ${games.length}  |  already embedded shots: ${done.size}`);

  let buf = [], ok = 0, fail = 0, skip = 0, n = 0;
  const sample = []; // for self-check
  for (const g of games) {
    const ids = g.screenshot_ids.slice(0, SHOTS);
    for (let shot = 0; shot < ids.length; shot++) {
      const key = `${g.id}:${shot}`;
      if (done.has(key)) { skip++; continue; }
      try {
        const v = await embed(ids[shot]);
        buf.push({ game_id: g.id, shot_idx: shot, embedding: JSON.stringify(v) });
        if (SELFCHECK && sample.length < 8 && Math.random() < 0.2) sample.push({ game_id: g.id, v });
        ok++;
      } catch (e) {
        fail++;
        if (fail <= 10) log(`  miss ${key}: ${String(e).slice(0, 120)}`);
      }
      if (buf.length >= 100) { await insertBatch(buf); buf = []; }
    }
    if (++n % 100 === 0) log(`  ${n}/${games.length} games  (ok=${ok} skip=${skip} fail=${fail})`);
  }
  await insertBatch(buf);
  log(`DONE  ok=${ok}  skipped=${skip}  failed=${fail}`);

  if (SELFCHECK && sample.length) {
    log(`\nSelf-check: re-querying ${sample.length} stored shots through match_games_by_clip_oss ...`);
    let pass = 0;
    for (const s of sample) {
      const res = await getJSON(`${REST}/rpc/match_games_by_clip_oss`, {
        method: "POST", headers: { ...H, "Content-Type": "application/json" },
        body: JSON.stringify({ query: JSON.stringify(s.v), lim: 5 }),
      });
      const hit = res.some((g) => g.id === s.game_id);
      log(`  game ${s.game_id}: ${hit ? "OK (self in top-5)" : "MISS - top=" + (res[0] && res[0].id)}`);
      if (hit) pass++;
    }
    if (pass !== sample.length) { console.error(`Self-check FAILED (${pass}/${sample.length})`); process.exit(1); }
    log(`Self-check PASSED (${pass}/${sample.length})`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });

"use strict";
/* Popularity in the room, from arcade-social (the <meta name="arcade-social">
   URL, https://api.<domain>): the Hall of Fame board by the door, listing
   the best score on every game's leaderboards, and the likes that warm the
   most-loved cabinets' marquees. Only public reads, sent without
   credentials; when the service is missing, refuses or is slow, the board
   says so quietly and the marquees go by plays alone.

   Pure (the same under node, in tests/browser/hall_fame_test.cjs):

     HallFame.warmth(plays, likes)   -> {slug: 0..1}: how warm a cabinet's marquee
                                        glows; only the most played or liked warm up
     HallFame.valueText(board, v)    -> "12 days", "1,024 wins", "4.5 seconds"
     HallFame.champions(found, cabs) -> the board's rows, best known games first:
                                        [{game, board, name, value}], at most MAX
     HallFame.draw(ctx, w, h, view)  -> paints the board (a 2D canvas context)

   HallFame.load(api, cabinets, store) fetches what the board shows in one
   request (GET /v1/boards/top: every board's #1), kept for FRESH_MS in
   sessionStorage so walking round the hall never asks twice. Against an
   arcade-social without that route (a 404) it falls back to each game's
   boards, then each board's top entry, a few at a time. */
(function (root) {
  const LIKES_FULL = 30;
  const MAX = 6, FRESH_MS = 10 * 60 * 1000, AT_ONCE = 3, KEY = "arcade-hall.fame";
  const SLUG = /^[a-z][a-z0-9-]{1,30}$/, BOARD = /^[a-z0-9][a-z0-9-]{0,40}$/;

  const isCount = (v) => typeof v === "number" && isFinite(v) && v >= 0;

  // Plays as a share of the most played; likes (fewer, so square-rooted) of the most liked.
  function warmth(plays, likes) {
    const p = plays || {}, l = likes || {}, out = {};
    const maxP = Math.max(0, ...Object.values(p).filter(isCount)), maxL = Math.max(0, ...Object.values(l).filter(isCount));
    const totalL = Object.values(l).filter(isCount).reduce((a, b) => a + b, 0);
    const slugs = new Set([...Object.keys(p), ...Object.keys(l)]);
    for (const s of slugs) {
      const sp = maxP ? (isCount(p[s]) ? p[s] : 0) / maxP : 0;
      const sl = maxL ? Math.sqrt((isCount(l[s]) ? l[s] : 0) / maxL) : 0;
      // Likes count for more as there come to be more of them (a third, from LIKES_FULL on).
      const kl = 0.35 * Math.min(1, totalL / LIKES_FULL), score = (1 - kl) * sp + kl * sl;
      // Only the top end warms up: below 0.6 the marquee is as it was.
      const x = Math.min(1, Math.max(0, (score - 0.6) / 0.4));
      out[s] = +(x * x * (3 - 2 * x)).toFixed(3);
    }
    return out;
  }

  function valueText(board, value) {
    if (typeof value !== "number" || !isFinite(value)) return "";
    const whole = board && board.integer;
    const n = whole ? Math.round(value) : Math.round(value * 10) / 10;
    const num = n.toLocaleString("en-US", {maximumFractionDigits: whole ? 0 : 1});
    let unit = board && typeof board.unit === "string" ? board.unit.trim().slice(0, 16) : "";
    if (n === 1 && /[^s]s$/.test(unit)) unit = unit.slice(0, -1);
    return unit ? `${num} ${unit}` : num;
  }

  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "\u2026" : s);

  /* found: [{slug, board: {id, title, unit, integer}, top: {displayName, value} | null}];
     cabinets: the layout's, most played first (its order after the stage). */
  function champions(found, cabinets) {
    const order = new Map(cabinets.map((c, i) => [c.slug, i]));
    const title = new Map(cabinets.map((c) => [c.slug, c.title]));
    return (found || [])
      .filter((f) => f && f.top && typeof f.top.displayName === "string" && f.top.displayName && typeof f.top.value === "number"
        && title.has(f.slug))
      .sort((a, b) => order.get(a.slug) - order.get(b.slug))
      .slice(0, MAX)
      .map((f) => ({game: title.get(f.slug), board: clip(String(f.board.title || f.board.id), 34),
        name: clip(f.top.displayName, 20), value: valueText(f.board, f.top.value)}));
  }

  /* view: {rows, games: [titles with boards], open: [titles whose boards are all empty],
     state: "loading" | "ready" | "off"} */
  function draw(ctx, w, h, view) {
    ctx.fillStyle = "rgb(16,10,24)"; ctx.fillRect(0, 0, w, h);
    const gold = "rgb(255,214,96)";
    ctx.save();
    ctx.shadowBlur = 16; ctx.shadowColor = gold; ctx.strokeStyle = gold; ctx.lineWidth = 6;
    ctx.strokeRect(14, 14, w - 28, h - 28);
    ctx.restore();
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = `bold ${Math.round(h * 0.11)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
    ctx.fillStyle = gold;
    ctx.save(); ctx.shadowBlur = 12; ctx.shadowColor = "rgb(255,150,40)";
    ctx.fillText("\u2605 HALL OF FAME \u2605", w / 2, h * 0.13);
    ctx.restore();
    const rows = (view && view.rows) || [];
    // Fewer rows, larger: at most a sixth of the board each.
    const top = h * 0.25, line = (h * 0.64) / Math.max(rows.length, 3.8);
    if (rows.length) {
      // Boards nobody has topped yet, under the rest.
      const open = (view.open || []).slice(0, 4);
      if (open.length && rows.length < MAX) {
        ctx.textAlign = "center";
        ctx.font = `${Math.round(h * 0.045)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
        ctx.fillStyle = "rgb(205,192,235)";
        ctx.fillText(clip("Still open: " + open.join(" \u00b7 "), 64), w / 2, top + line * rows.length + h * 0.07);
      }
      rows.forEach((r, k) => {
        const y = top + line * (k + 0.5);
        ctx.fillStyle = k % 2 ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.07)";
        ctx.fillRect(34, y - line / 2 + 3, w - 68, line - 6);
        ctx.textAlign = "left";
        ctx.font = `bold ${Math.round(line * 0.36)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
        ctx.fillStyle = "rgb(255,236,190)";
        ctx.fillText(r.name, 54, y - line * 0.15);
        ctx.font = `${Math.round(line * 0.27)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
        ctx.fillStyle = "rgb(205,192,235)";
        ctx.fillText(`${r.game} \u00b7 ${r.board}`, 54, y + line * 0.25);
        ctx.textAlign = "right";
        ctx.font = `bold ${Math.round(line * 0.36)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
        ctx.fillStyle = gold;
        ctx.fillText(r.value, w - 54, y);
      });
    } else {
      const games = (view && view.games) || [];
      ctx.textAlign = "center";
      ctx.font = `bold ${Math.round(h * 0.075)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
      ctx.fillStyle = "rgb(255,236,190)";
      const said = !view || view.state === "loading" ? "Counting the scores\u2026"
        : view.state === "off" ? "Scores are resting" : "No champions yet";
      ctx.fillText(said, w / 2, h * 0.45);
      ctx.font = `${Math.round(h * 0.05)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
      ctx.fillStyle = "rgb(190,176,220)";
      if (view && view.state === "ready") {
        ctx.fillText(games.length ? "Set the first score in:" : "Leaderboards are coming to the games", w / 2, h * 0.6);
        if (games.length) ctx.fillText(clip(games.join(" \u00b7 "), 60), w / 2, h * 0.7);
      }
    }
    ctx.textAlign = "center";
    ctx.font = `${Math.round(h * 0.04)}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
    ctx.fillStyle = "rgba(190,176,220,0.7)";
    ctx.fillText("The best score on each game's leaderboard \u00b7 sign in to a game to post yours", w / 2, h * 0.94);
  }

  /* ----------------------------------------------------- fetching */
  // {status, body}: status 0 when the request itself failed; body null unless 2xx JSON.
  async function request(api, path) {
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), 8000) : 0;
    try {
      const res = await fetch(api + path, Object.assign({headers: {accept: "application/json"}, credentials: "omit"},
        ctl ? {signal: ctl.signal} : {}));
      return {status: res.status || (res.ok ? 200 : 0), body: res.ok ? await res.json() : null};
    } catch (e) { return {status: 0, body: null}; } finally { clearTimeout(timer); }
  }

  async function getJson(api, path) { return (await request(api, path)).body; }

  async function pool(items, fn) {
    const out = [];
    let next = 0;
    const worker = async () => { while (next < items.length) { const k = next++; out[k] = await fn(items[k]); } };
    await Promise.all([...Array(Math.min(AT_ONCE, items.length))].map(worker));
    return out;
  }

  function cached(store) {
    try {
      const v = JSON.parse(store.getItem(KEY) || "null");
      return v && Date.now() - v.at < FRESH_MS && Array.isArray(v.found) ? v : null;
    } catch (e) { return null; }
  }

  const boardOf = (b) => ({id: b.id, title: b.title, unit: b.unit, integer: !!b.integer});
  const topOf = (e) => (e && typeof e === "object" ? {displayName: e.displayName, value: e.value} : null);

  /* One request: [{slug, board, top}] for every board of every game, kept to the
     hall's deployed cabinets in the service's order. null when the route may be
     missing: a 404, or a failed request, since an arcade-social from before the
     route answers its 404 without CORS headers and the page sees only a network
     error. false when the service answered but failed (429, 5xx, bad JSON). */
  async function loadAll(api, slugs) {
    const {status, body} = await request(api, "/v1/boards/top");
    if (status === 404 || status === 0) return null;
    if (!body || !Array.isArray(body.boards)) return false;
    const wanted = new Set(slugs);
    return body.boards.filter((f) => f && typeof f.slug === "string" && wanted.has(f.slug) && f.board
      && typeof f.board.id === "string" && BOARD.test(f.board.id))
      .map((f) => ({slug: f.slug, board: boardOf(f.board), top: topOf(f.top)}));
  }

  // Before /v1/boards/top: each game's boards, then each board's #1, a few at a time.
  async function loadEach(api, slugs) {
    const decl = await pool(slugs, (s) => getJson(api, `/v1/games/${s}/boards`));
    if (decl.every((d) => d === null)) return false;
    const boards = [];
    decl.forEach((d, k) => {
      for (const b of (d && Array.isArray(d.boards) ? d.boards : [])) {
        if (b && typeof b.id === "string" && BOARD.test(b.id)) boards.push({slug: slugs[k], board: b});
      }
    });
    const tops = await pool(boards, (b) => getJson(api, `/v1/boards/${b.slug}/${b.board.id}?limit=1`));
    return boards.map((b, k) => ({slug: b.slug, board: boardOf(b.board),
      top: topOf(tops[k] && Array.isArray(tops[k].entries) ? tops[k].entries[0] : null)}));
  }

  async function load(api, cabinets, store) {
    const hit = store && cached(store);
    if (hit) return hit;
    const slugs = cabinets.filter((c) => c.deployed && SLUG.test(c.slug)).map((c) => c.slug);
    let found = await loadAll(api, slugs);
    if (found === null) found = await loadEach(api, slugs);
    if (found === false) return {at: Date.now(), found: [], games: [], off: true};
    const doc = {at: Date.now(), found, games: [...new Set(found.map((f) => f.slug))], off: false};
    try { if (store) store.setItem(KEY, JSON.stringify(doc)); } catch (e) { /* private window */ }
    return doc;
  }

  async function likes(api) {
    const body = await getJson(api, "/v1/likes/counts");
    const out = {};
    if (body && typeof body === "object" && !Array.isArray(body)) {
      for (const [s, n] of Object.entries(body)) if (SLUG.test(s) && isCount(n)) out[s] = Math.floor(n);
    }
    return body ? out : null;
  }

  // The games whose boards nobody has topped yet (found: load()'s), by title.
  function open(found, cabinets) {
    const title = new Map(cabinets.map((c) => [c.slug, c.title])), topped = new Set();
    for (const f of found || []) if (f && f.top) topped.add(f.slug);
    return [...new Set((found || []).filter((f) => f && !topped.has(f.slug) && title.has(f.slug)).map((f) => title.get(f.slug)))];
  }

  const HallFame = {open, warmth, valueText, champions, draw, load, likes, MAX, FRESH_MS};
  if (typeof module !== "undefined" && module.exports) module.exports = HallFame;
  else root.HallFame = HallFame;
})(typeof window !== "undefined" ? window : globalThis);

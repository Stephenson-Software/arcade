"use strict";
/* Walk replays (RFC 0030 §3): "Share my walk anonymously" and "The hall today".

   The maths has no DOM and no engine, so it runs under node too
   (tests/browser/hall_replays_test.cjs):

     HallReplays.recorder()                 -> {sample(p), visit(slug), payload(key), points, full}
                                               a coarse path: 0.5 s samples rounded to 0.25 m,
                                               at most 120 points and 10 cabinets
     HallReplays.plan(walk, layout, world, W) -> a walk ready to play in this hall, or null:
                                               as recorded when the layout key matches, else
                                               re-anchored to its cabinets by slug
     HallReplays.pose(plan, t)              -> {x, z, yaw, alpha, cabinet} at t s into its loop,
                                               or null between loops
     HallReplays.people(plans, t, opts)     -> the list for HallPeople.set("replays", ...)

   In the page it adds the opt-in (a checkbox in Settings, off by default and
   kept in localStorage; nothing is recorded while it is off), uploads the
   walk once (sendBeacon when the page is hidden or left, or when a game
   opens) and plays "the hall today" (a button in the help panel, shown only
   when arcade has enough walks to show; ?replay=today starts it) through
   window.HallPeople (hall-people.js), when that is loaded. */
(function (root) {
  const DT = 0.5;            // s between samples
  const GRID = 0.25;         // m: points are rounded to this
  const MAX_POINTS = 120, MAX_VISITS = 10, MIN_POINTS = 4;
  const STEP = 2.4;          // m: a longer gap between samples (a late timer) is filled in
  const JUMP = 10;           // m: a longer one is not walking (a link, a reload): recording stops
  const SPEED = 1.5;         // playback runs this much faster than the walk (standing is already cut)
  const PAUSE = 2.5;         // s a figure stands at each cabinet it visited
  const FADE = 0.6;          // s to fade in and out
  const GAP = 2;             // s hidden between loops
  const COLOR = [0.74, 0.78, 0.88], ALPHA = 0.42;
  const WALK = 2.4;          // m/s (hall-walk.js), for re-anchored walks

  const round = (v) => Math.round(v / GRID) * GRID + 0;

  function recorder() {
    const points = [], visits = [];
    let full = false, lastVisit = null;
    function push(x, z) {
      if (points.length >= MAX_POINTS) { full = true; return; }
      points.push([round(x), round(z)]);
    }
    return {
      points, visits,
      get full() { return full; },
      sample(p) {
        if (full || !p) return;
        const x = round(p.x), z = round(p.z);
        if (!points.length) { push(x, z); return; }
        const [lx, lz] = points[points.length - 1];
        const d = Math.hypot(x - lx, z - lz);
        if (d < GRID * 0.5) return;  // standing still adds nothing
        if (d > JUMP) {
          // Not a walk: keep what came before, or start again if that was nothing.
          if (points.length < MIN_POINTS) { points.length = 0; visits.length = 0; lastVisit = null; push(x, z); }
          else full = true;
          return;
        }
        const n = Math.ceil(d / STEP);
        for (let i = 1; i <= n && !full; i++) push(lx + (x - lx) * i / n, lz + (z - lz) * i / n);
      },
      visit(slug) {
        if (!slug || slug === lastVisit || !points.length || full) return;
        lastVisit = slug;
        if (visits.length < MAX_VISITS) visits.push({slug, at: points.length - 1});
      },
      payload(key) {
        if (points.length < MIN_POINTS || !key) return null;
        return {layout: key, dt: DT, points: points.map((p) => p.slice()), visits: visits.map((v) => Object.assign({}, v))};
      },
    };
  }

  /* A route between two spots that walks round the cabinets: A* over a
     0.5 m grid of clear spots (built once per hall), then pulled straight
     wherever the way is clear, so a figure takes the aisles. */
  const CELL = 0.5;
  function grid(world, W) {
    if (world.__replayGrid) return world.__replayGrid;
    const b = world.bounds, x0 = b[0] + CELL / 2, z0 = b[1] + CELL / 2;
    const nx = Math.max(1, Math.floor((b[2] - b[0]) / CELL)), nz = Math.max(1, Math.floor((b[3] - b[1]) / CELL));
    const ok = new Uint8Array(nx * nz);
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) ok[j * nx + i] = W.clear(x0 + i * CELL, z0 + j * CELL, world) ? 1 : 0;
    const g = {x0, z0, nx, nz, ok, at: (i, j) => [x0 + i * CELL, z0 + j * CELL]};
    Object.defineProperty(world, "__replayGrid", {value: g});
    return g;
  }
  function nearestCell(g, x, z) {
    const ci = Math.round((x - g.x0) / CELL), cj = Math.round((z - g.z0) / CELL);
    let best = -1, bestD = Infinity;
    for (let r = 0; r < 8 && best < 0; r++) {
      for (let j = cj - r; j <= cj + r; j++) for (let i = ci - r; i <= ci + r; i++) {
        if (i < 0 || j < 0 || i >= g.nx || j >= g.nz || !g.ok[j * g.nx + i]) continue;
        const [px, pz] = g.at(i, j), d = Math.hypot(px - x, pz - z);
        if (d < bestD) { bestD = d; best = j * g.nx + i; }
      }
    }
    return best;
  }
  /* Whether a figure can walk straight from a to b: every 0.25 m along it is
     in a clear cell (a clear cell's centre is clear by the visitor's radius,
     so a point in it is clear by at least 0.1 m). */
  function sees(a, b, world, W) {
    const g = grid(world, W), d = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.ceil(d / 0.25));
    for (let k = 1; k < n; k++) {
      const i = Math.round((a[0] + (b[0] - a[0]) * k / n - g.x0) / CELL), j = Math.round((a[1] + (b[1] - a[1]) * k / n - g.z0) / CELL);
      if (i < 0 || j < 0 || i >= g.nx || j >= g.nz || !g.ok[j * g.nx + i]) return false;
    }
    return true;
  }
  function route(a, b, world, W) {
    if (sees(a, b, world, W)) return [a, b];
    const g = grid(world, W), s = nearestCell(g, a[0], a[1]), e = nearestCell(g, b[0], b[1]);
    if (s < 0 || e < 0) return null;
    const n = g.nx * g.nz, cost = new Float64Array(n).fill(Infinity), from = new Int32Array(n).fill(-1), shut = new Uint8Array(n);
    const [ex, ez] = g.at(e % g.nx, Math.floor(e / g.nx));
    const h = (c) => { const [x, z] = g.at(c % g.nx, Math.floor(c / g.nx)); return Math.hypot(x - ex, z - ez); };
    // A binary heap of [f, cell].
    const heap = [[h(s), s]];
    const pushH = (item) => { heap.push(item); for (let k = heap.length - 1; k;) { const p = (k - 1) >> 1;
      if (heap[p][0] <= heap[k][0]) break; [heap[p], heap[k]] = [heap[k], heap[p]]; k = p; } };
    const popH = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last;
      for (let k = 0; ;) { const l = 2 * k + 1, r = l + 1; let m = k;
        if (l < heap.length && heap[l][0] < heap[m][0]) m = l; if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
        if (m === k) break; [heap[m], heap[k]] = [heap[k], heap[m]]; k = m; } } return top[1]; };
    cost[s] = 0;
    while (heap.length) {
      const c = popH();
      if (c === e) break;
      if (shut[c]) continue;
      shut[c] = 1;
      const ci = c % g.nx, cj = Math.floor(c / g.nx);
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        if (!di && !dj) continue;
        const i = ci + di, j = cj + dj;
        if (i < 0 || j < 0 || i >= g.nx || j >= g.nz || !g.ok[j * g.nx + i]) continue;
        if (di && dj && (!g.ok[cj * g.nx + i] || !g.ok[j * g.nx + ci])) continue;  // no corner cutting
        const m = j * g.nx + i, nc = cost[c] + (di && dj ? Math.SQRT2 : 1) * CELL;
        if (nc < cost[m]) { cost[m] = nc; from[m] = c; pushH([nc + h(m), m]); }
      }
    }
    if (from[e] < 0 && e !== s) return null;
    const cells = [];
    for (let c = e; c >= 0; c = c === s ? -1 : from[c]) cells.push(g.at(c % g.nx, Math.floor(c / g.nx)));
    const path = [a].concat(cells.reverse(), [b]);
    // Pulled straight: from each point, on to the furthest one in clear sight.
    const out = [path[0]];
    for (let i = 0; i < path.length - 1;) {
      let j = i + 1;
      while (j < path.length - 1 && sees(path[i], path[j + 1], world, W)) j++;
      out.push(path[j]); i = j;
    }
    return out;
  }

  /* A walk from GET /api/walks/today, ready to play in this hall. */
  function plan(walk, layout, world, W) {
    if (!walk || !Array.isArray(walk.points) || walk.points.length < 2) return null;
    const bySlug = new Map(layout.cabinets.map((c) => [c.slug, c]));
    const pts = [], stops = new Map(), secs = [0];
    if (walk.layout === layout.layoutKey) {
      for (const [x, z] of walk.points.slice(0, MAX_POINTS)) {
        const p = W.resolve(x, z, world);
        if (pts.length) secs.push(DT / SPEED);
        pts.push([p.x, p.z]);
      }
      for (const v of walk.visits || []) {
        const c = bySlug.get(v.slug);
        if (c && v.at >= 0 && v.at < pts.length) stops.set(v.at, {slug: v.slug, yaw: W.front(c).yaw});
      }
    } else {
      // The cabinets have moved since: walk from where it began to each cabinet
      // it visited that is still here, round the others, standing at each.
      const s = W.settle(walk.points[0][0], walk.points[0][1], world);
      pts.push([s.x, s.z]);
      for (const v of (walk.visits || []).slice(0, MAX_VISITS)) {
        const c = bySlug.get(v.slug);
        if (!c) continue;
        const f = W.front(c), from = pts[pts.length - 1];
        const way = route(from, [f.x, f.z], world, W);
        if (!way) continue;
        for (const p of way.slice(1)) {
          secs.push(Math.hypot(p[0] - pts[pts.length - 1][0], p[1] - pts[pts.length - 1][1]) / (WALK * SPEED));
          pts.push(p);
        }
        stops.set(pts.length - 1, {slug: v.slug, yaw: f.yaw});
      }
      if (!stops.size) return null;
    }
    // When it reaches each point, and when it leaves it.
    const arrive = [], depart = [];
    let t = FADE;
    for (let i = 0; i < pts.length; i++) {
      t += secs[i];
      arrive.push(t);
      if (stops.has(i)) t += PAUSE;
      depart.push(t);
    }
    const end = t + FADE;
    return {pts, stops, arrive, depart, end, loop: end + GAP};
  }

  function yawOf(dx, dz) { return Math.atan2(-dz, -dx); }  // looking along (-cos yaw, -sin yaw)

  function pose(p, t) {
    t = ((t % p.loop) + p.loop) % p.loop;
    if (t >= p.end) return null;
    const n = p.pts.length;
    const alpha = ALPHA * Math.min(1, t / FADE, (p.end - t) / FADE);
    const travel = (i) => { const j = Math.min(i + 1, n - 1), k = j === i ? i - 1 : i;
      return yawOf(p.pts[j][0] - p.pts[k][0], p.pts[j][1] - p.pts[k][1]); };
    let i = 0;
    while (i < n - 1 && p.arrive[i + 1] <= t) i++;
    const at = p.pts[i], stop = p.stops.get(i);
    if (t < p.depart[i] || i === n - 1) {
      return {x: at[0], z: at[1], yaw: stop ? stop.yaw : travel(Math.max(0, i - 1)), alpha, cabinet: stop ? stop.slug : null};
    }
    const k = (t - p.depart[i]) / (p.arrive[i + 1] - p.depart[i]), b = p.pts[i + 1];
    return {x: at[0] + (b[0] - at[0]) * k, z: at[1] + (b[1] - at[1]) * k, yaw: travel(i), alpha, cabinet: null};
  }

  /* Where a walk ends up when nothing may move (reduced motion): standing at
     the last cabinet it visited, or where it stopped. */
  function rest(p) {
    let i = p.pts.length - 1, stop = null, best = -1;
    for (const [k, s] of p.stops) if (k > best) { best = k; stop = s; }
    if (stop) i = best;
    const at = p.pts[i];
    return {x: at[0], z: at[1], yaw: stop ? stop.yaw : 0, alpha: ALPHA, cabinet: stop ? stop.slug : null};
  }

  function people(plans, t, opts = {}) {
    const out = [];
    plans.forEach((p, i) => {
      if (!p) return;
      // Staggered, so they do not move in step.
      const q = opts.reduced ? rest(p) : pose(p, t + ((i * 0.6180339887) % 1) * p.loop);
      if (q) out.push({id: "replay-" + i, x: q.x, z: q.z, yaw: q.yaw, color: COLOR.slice(), alpha: q.alpha,
        cabinet: q.cabinet || undefined});
    });
    return out;
  }

  const HallReplays = {recorder, plan, pose, rest, people, DT, GRID, MAX_POINTS, MAX_VISITS, MIN_POINTS, STEP, JUMP,
    SPEED, PAUSE};
  if (typeof module !== "undefined" && module.exports) { module.exports = HallReplays; return; }
  root.HallReplays = HallReplays;
  if (typeof document === "undefined" || !document.getElementById("hall")) return;

  /* ------------------------------------------------------------ the page */
  const $ = (id) => document.getElementById(id);
  const SHARE_KEY = "arcade-hall.shareWalk";
  const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
  const read = () => { try { return store && store.getItem(SHARE_KEY) === "1"; } catch (e) { return false; } };
  const write = (on) => { try { if (store) { if (on) store.setItem(SHARE_KEY, "1"); else store.removeItem(SHARE_KEY); } } catch (e) { /* blocked */ } };
  const params = new URLSearchParams(location.search);
  const hall = () => window.__hall;
  const api = new URL("../api/walks", location.href).pathname;

  let sharing = read(), rec = sharing ? recorder() : null, sent = null, done = false;
  const box = $("set-walk");
  if (box) {
    box.checked = sharing;
    box.addEventListener("change", () => setSharing(box.checked));
  }
  // Reset to defaults turns it off too (its default).
  const reset = $("set-reset");
  if (reset) reset.addEventListener("click", () => { setSharing(false); if (box) box.checked = false; });
  function setSharing(on) {
    sharing = !!on;
    write(sharing);
    // Off throws away what was recorded; on starts from here.
    rec = sharing && !done ? recorder() : null;
  }

  function upload() {
    if (done) return;
    const h = hall();
    const body = rec && sharing && h && h.layout ? rec.payload(h.layout.layoutKey) : null;
    if (!body) return;
    done = true; sent = body; rec = null;
    const text = JSON.stringify(body);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(api, new Blob([text], {type: "application/json"}))) return;
    } catch (e) { /* fall through */ }
    try { fetch(api, {method: "POST", body: text, headers: {"Content-Type": "application/json"}, keepalive: true}).catch(() => {}); } catch (e) { /* offline */ }
  }
  window.addEventListener("pagehide", upload);
  document.addEventListener("visibilitychange", () => { if (document.hidden) upload(); });

  /* Recording: twice a second, while the hall is walked. */
  setInterval(() => {
    const h = hall();
    if (!rec || !sharing || done || !h || !h.me || !h.layout || document.hidden) return;
    if (h.move && h.move !== "idle") { upload(); return; }  // a game is opening
    rec.sample(h.me);
    rec.visit(h.near);
  }, DT * 1000);

  /* "The hall today". */
  const btn = $("today-btn");
  let walks = [], plans = [], playing = false, t0 = 0, last = [], timer = 0, fetched = false;
  const feed = (list) => { last = list; if (window.HallPeople) window.HallPeople.set("replays", list); };
  function say(text) { const a = $("announce"); if (a) a.textContent = text; }
  function show() {
    if (!btn) return;
    btn.setAttribute("aria-pressed", String(playing));
    btn.textContent = playing ? "The hall today: on" : "The hall today";
  }
  function tick() {
    const h = hall();
    if (!h || (h.move && h.move !== "idle")) return;
    const reduced = !!(h.settings && h.settings.reducedMotion);
    feed(people(plans, (performance.now() - t0) / 1000, {reduced}));
  }
  function start() {
    const h = hall();
    if (!h || !h.layout || !window.HallWalk) return false;
    const W = window.HallWalk, world = W.world(h.layout);
    plans = walks.map((w) => plan(w, h.layout, world, W)).filter(Boolean);
    if (!plans.length) { say("No walks to show from today yet."); return false; }
    playing = true; t0 = performance.now();
    clearInterval(timer); timer = setInterval(tick, 125); tick();
    show();
    say("Showing walks visitors left in the hall today, as grey figures.");
    return true;
  }
  function stop() {
    playing = false; clearInterval(timer); timer = 0; feed([]); show();
  }
  if (btn) btn.addEventListener("click", () => (playing ? stop() : start()));

  async function load() {
    try {
      const res = await fetch(api + "/today", {cache: "no-cache"});
      if (!res.ok) return;
      const doc = await res.json();
      walks = Array.isArray(doc.walks) ? doc.walks : [];
    } catch (e) { walks = []; }
    fetched = true;
    // Hidden when there is nothing (or too little) to show.
    if (btn) btn.hidden = !walks.length;
    if (params.get("replay") === "today") start();
  }
  (function wait() {
    const h = hall();
    if (h && h.layout && h.me) load(); else setTimeout(wait, 250);
  })();

  window.__hallReplays = {
    get sharing() { return sharing; },
    get recorded() { return rec ? {points: rec.points.length, visits: rec.visits.map((v) => v.slug)} : null; },
    get sent() { return sent; },
    get playing() { return playing; },
    get fetched() { return fetched; },
    get walks() { return walks.length; },
    get people() { return last; },
    start, stop, upload,
  };
})(typeof window !== "undefined" ? window : globalThis);

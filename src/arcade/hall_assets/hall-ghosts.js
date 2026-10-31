"use strict";
/* Ghosts of recent visitors (RFC 0030 §2): anonymous figures that drift in
   through the door, walk the aisles to the cabinets people have been
   playing lately, stand at one for a while as if playing, and leave. They
   stand for no particular person: their number comes from GET /api/activity,
   a 0..4 level per game over the last seven complete UTC days (nothing below
   k plays), and everything else is made up here from a seeded generator.

   The maths has no DOM and no engine, so it runs under node
   (tests/browser/hall_ghosts_test.cjs):

     HallGhosts.rng(seed)                    -> () => 0..1, deterministic
     HallGhosts.budget({economy, phone})     -> the most ghosts to draw (12, or 6 on phones / in economy)
     HallGhosts.target(levels, layout, cap)  -> how many ghosts the hall should hold now
     HallGhosts.grid(layout, world)          -> a walkable grid of the floor
     HallGhosts.route(grid, from, to)        -> waypoints around the cabinets, [{x, z}, ...]
     HallGhosts.crowd(layout, levels, opts)  -> a crowd: step(dt) -> people for HallPeople.set("ghosts", ...)

   In the page, HallGhosts.start() waits for the hall, fetches the levels
   and feeds window.HallPeople (hall-people.js draws them), ten times a
   second, while the "Show ghosts of recent visitors" setting is on. Ghosts
   never block the visitor and never touch the camera. Under reduce motion
   they stand at their cabinets and do not walk. */
(function (root) {
  const W = typeof module !== "undefined" && module.exports ? require("./hall-walk.js") : root.HallWalk;

  const CAP = 12, CAP_LOW = 6;       // RFC 0030 §1: 12 on desktop, 6 in economy (and on phones)
  const RADIUS = 0.3;                // a ghost, for keeping clear of cabinets
  const CELL = 0.4;                  // the walkable grid's cell, metres
  const SPEED = [0.9, 1.25];         // m/s: an amble, slower than the visitor's 2.4
  const PLAY = [20, 90];             // s standing at a cabinet (RFC 0030 §2.4)
  const ARRIVE = [2.5, 9];           // s between one ghost coming in and the next
  const AGAIN = 0.35;                // the chance of walking to another cabinet instead of leaving
  const FADE = 1.2;                  // s to fade in or out
  const ALPHA = 0.55;                // a ghost is never solid
  const COLOUR = [0.74, 0.80, 0.90]; // neutral, a little cold
  const STAND = 0.5;                 // m in front of a cabinet's control deck

  /* mulberry32: small, fast, and the same sequence everywhere. */
  function rng(seed) {
    let a = (seed >>> 0) || 0x9e3779b9;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const between = (r, [lo, hi]) => lo + (hi - lo) * r();

  function budget(opts) {
    opts = opts || {};
    return opts.economy || opts.phone ? CAP_LOW : CAP;
  }

  function levelOf(levels, slug) {
    const v = levels && levels[slug];
    return Number.isInteger(v) ? Math.max(0, Math.min(4, v)) : 0;
  }
  /* The lit cabinets with any activity, and their levels. */
  function busy(levels, layout) {
    return layout.cabinets.filter((c) => c.lit !== false && levelOf(levels, c.slug) > 0)
      .map((c) => ({c, level: levelOf(levels, c.slug)}));
  }
  /* One ghost per level point (RFC 0030 §2.4), but never more than the
     cabinets have places for, and never more than the cap. */
  function target(levels, layout, cap) {
    let n = 0;
    for (const b of busy(levels, layout)) n += Math.min(b.level, slots(b.level));
    return Math.min(n, cap == null ? CAP : cap);
  }
  // A busy cabinet has room for a second figure, beside the player, watching.
  function slots(level) { return level >= 3 ? 2 : 1; }

  /* ---------------------------------------------------------- routes */
  function grid(layout, world) {
    world = world || W.world(layout);
    const b = world.bounds;
    const x0 = b[0], z0 = b[1];
    const nx = Math.max(1, Math.floor((b[2] - b[0]) / CELL)), nz = Math.max(1, Math.floor((b[3] - b[1]) / CELL));
    const open = new Uint8Array(nx * nz);
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
      open[j * nx + i] = W.clear(x0 + (i + 0.5) * CELL, z0 + (j + 0.5) * CELL, world, RADIUS) ? 1 : 0;
    }
    return {x0, z0, nx, nz, open, world};
  }
  function cellOf(g, x, z) {
    const i = Math.max(0, Math.min(g.nx - 1, Math.floor((x - g.x0) / CELL)));
    const j = Math.max(0, Math.min(g.nz - 1, Math.floor((z - g.z0) / CELL)));
    return [i, j];
  }
  const centre = (g, i, j) => ({x: g.x0 + (i + 0.5) * CELL, z: g.z0 + (j + 0.5) * CELL});
  /* The nearest open cell to (i, j). */
  function nearestOpen(g, i, j) {
    if (g.open[j * g.nx + i]) return [i, j];
    for (let r = 1; r < Math.max(g.nx, g.nz); r++) {
      let best = null, bestD = Infinity;
      for (let dj = -r; dj <= r; dj++) for (let di = -r; di <= r; di++) {
        if (Math.max(Math.abs(di), Math.abs(dj)) !== r) continue;
        const a = i + di, b = j + dj;
        if (a < 0 || b < 0 || a >= g.nx || b >= g.nz || !g.open[b * g.nx + a]) continue;
        const d = di * di + dj * dj;
        if (d < bestD) { bestD = d; best = [a, b]; }
      }
      if (best) return best;
    }
    return [i, j];
  }
  /* Whether a straight walk from a to b stays clear (sampled every 10 cm). */
  function sight(g, a, b) {
    const d = Math.hypot(b.x - a.x, b.z - a.z), n = Math.ceil(d / 0.1);
    for (let k = 1; k < n; k++) {
      const t = k / n;
      if (!W.clear(a.x + (b.x - a.x) * t, a.z + (b.z - a.z) * t, g.world, RADIUS * 0.9)) return false;
    }
    return true;
  }
  /* A* over the grid (8-connected, no corner cutting), then the corners
     pulled straight wherever the way is clear. The ends are the exact
     points asked for. */
  function route(g, from, to) {
    const [si, sj] = nearestOpen(g, ...cellOf(g, from.x, from.z));
    const [ti, tj] = nearestOpen(g, ...cellOf(g, to.x, to.z));
    const N = g.nx * g.nz, start = sj * g.nx + si, goal = tj * g.nx + ti;
    const cost = new Float64Array(N).fill(Infinity), prev = new Int32Array(N).fill(-1), done = new Uint8Array(N);
    const heap = [];
    const push = (k, f) => {
      heap.push([f, k]);
      for (let i = heap.length - 1; i > 0;) {
        const p = (i - 1) >> 1;
        if (heap[p][0] <= heap[i][0]) break;
        [heap[p], heap[i]] = [heap[i], heap[p]]; i = p;
      }
    };
    const pop = () => {
      const top = heap[0], last = heap.pop();
      if (heap.length) {
        heap[0] = last;
        for (let i = 0; ;) {
          const l = 2 * i + 1, r = l + 1;
          let m = i;
          if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
          if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
          if (m === i) break;
          [heap[m], heap[i]] = [heap[i], heap[m]]; i = m;
        }
      }
      return top;
    };
    const h = (k) => Math.hypot((k % g.nx) - ti, Math.floor(k / g.nx) - tj);
    cost[start] = 0; push(start, h(start));
    while (heap.length) {
      const [, k] = pop();
      if (done[k]) continue;
      done[k] = 1;
      if (k === goal) break;
      const i = k % g.nx, j = Math.floor(k / g.nx);
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        if (!di && !dj) continue;
        const a = i + di, b = j + dj;
        if (a < 0 || b < 0 || a >= g.nx || b >= g.nz) continue;
        const n = b * g.nx + a;
        if (!g.open[n] || done[n]) continue;
        if (di && dj && (!g.open[j * g.nx + a] || !g.open[b * g.nx + i])) continue;
        const c = cost[k] + (di && dj ? Math.SQRT2 : 1);
        if (c < cost[n]) { cost[n] = c; prev[n] = k; push(n, c + h(n)); }
      }
    }
    const cells = [];
    if (goal === start || prev[goal] !== -1) {
      for (let k = goal; k !== -1; k = prev[k]) { cells.push(centre(g, k % g.nx, Math.floor(k / g.nx))); if (k === start) break; }
      cells.reverse();
    }
    const pts = [{x: from.x, z: from.z}, ...cells, {x: to.x, z: to.z}];
    // String pulling: from each kept point, jump to the furthest one in sight.
    const out = [pts[0]];
    for (let a = 0; a < pts.length - 1;) {
      let b = pts.length - 1;
      while (b > a + 1 && !sight(g, pts[a], pts[b])) b--;
      out.push(pts[b]); a = b;
    }
    return out;
  }

  /* ------------------------------------------------------------ places */
  /* Where a ghost stands at a cabinet: slot 0 plays, square on; slot 1
     watches from beside and a little back, turned towards the screen. */
  function place(c, slot, world) {
    const fr = W.frame(c);
    const lx = slot ? 0.62 : 0, lz = 0.72 + STAND + (slot ? 0.35 : 0);
    const p = fr.p(lx, 0, lz);
    const at = W.settle(p[0], p[2], world);
    const s = fr.p(0, 1.4, 0.3);  // the screen
    return {x: at.x, z: at.z, yaw: Math.atan2(at.z - s[2], at.x - s[0])};
  }
  /* The door: on the near wall (+z), in the middle of the opening. */
  function door(layout, world) {
    const s = W.spawn(layout), b = world.bounds;
    const inside = W.settle(s.x, s.z, world);
    return {outside: {x: s.x, z: b[3] - RADIUS - 0.02}, inside};
  }
  // The yaw that looks along (dx, dz) (hall-walk.js: looking is (-cos, -sin)).
  const yawOf = (dx, dz) => Math.atan2(-dz, -dx);

  /* ------------------------------------------------------------ crowd */
  /* opts: {seed, cap, reduced}. levels: {slug: 0..4}. */
  function crowd(layout, levels, opts) {
    opts = opts || {};
    const world = W.world(layout), g = grid(layout, world), r = rng(opts.seed == null ? 1 : opts.seed);
    const gate = door(layout, world);
    let cap = opts.cap == null ? CAP : opts.cap, reduced = !!opts.reduced;
    let lv = Object.assign({}, levels || {}), clock = 0, nextArrival = 0, made = 0;
    const ghosts = [];
    const taken = new Map();  // "slug#slot" -> ghost

    function wanted() { return target(lv, layout, cap); }
    /* A free place, weighted by level: busier cabinets more often. */
    function choose(except) {
      const options = [];
      for (const {c, level} of busy(lv, layout)) {
        if (except && c.slug === except) continue;
        for (let s = 0; s < slots(level); s++) {
          if (!taken.has(c.slug + "#" + s)) { options.push({c, s, w: level * (s ? 0.5 : 1)}); break; }
        }
      }
      if (!options.length) return null;
      let pick = r() * options.reduce((a, o) => a + o.w, 0);
      for (const o of options) { pick -= o.w; if (pick <= 0) return o; }
      return options[options.length - 1];
    }
    function claim(gh, o) {
      if (gh.claim) taken.delete(gh.claim);
      gh.claim = o ? o.c.slug + "#" + o.s : null;
      if (o) taken.set(gh.claim, gh);
    }
    function walkTo(gh, to, then) {
      gh.path = route(g, gh, to); gh.leg = 1; gh.state = then; gh.goal = to;
    }
    function spawn(atCabinet) {
      const o = choose();
      if (!o) return null;
      const gh = {id: "ghost-" + (++made), speed: between(r, SPEED), alpha: 0, fade: 1, claim: null, cabinet: null};
      claim(gh, o);
      gh.spot = place(o.c, o.s, world); gh.slug = o.c.slug;
      if (atCabinet) {
        Object.assign(gh, {x: gh.spot.x, z: gh.spot.z, yaw: gh.spot.yaw, state: "play", cabinet: o.s ? null : o.c.slug,
          until: clock + between(r, PLAY) * (0.3 + 0.7 * r())});
      } else {
        Object.assign(gh, {x: gate.outside.x + (r() - 0.5) * 0.8, z: gate.outside.z, yaw: Math.PI / 2});
        walkTo(gh, gh.spot, "walk");
      }
      ghosts.push(gh);
      return gh;
    }
    function leave(gh) {
      claim(gh, null); gh.cabinet = null;
      walkTo(gh, {x: gate.outside.x + (r() - 0.5) * 0.8, z: gate.outside.z}, "leave");
    }

    // At the start, about half the ghosts are already at their cabinets
    // (the hall has been open a while); the rest come in through the door.
    // Under reduce motion all of them are, and nobody walks.
    for (let n = wanted(), k = 0; k < n; k++) {
      if (!(reduced || k < Math.ceil(n / 2))) break;
      spawn(true);
    }
    nextArrival = between(r, [0.5, 3]);

    function move(gh, dt) {
      let left = gh.speed * dt;
      while (left > 1e-6 && gh.leg < gh.path.length) {
        const p = gh.path[gh.leg], dx = p.x - gh.x, dz = p.z - gh.z, d = Math.hypot(dx, dz);
        if (d < 1e-6) { gh.leg++; continue; }
        const s = Math.min(left, d);
        gh.x += dx / d * s; gh.z += dz / d * s; left -= s;
        // Turn towards where it walks, smoothly.
        let dy = yawOf(dx, dz) - gh.yaw;
        dy = Math.atan2(Math.sin(dy), Math.cos(dy));
        gh.yaw += dy * Math.min(1, dt * 6);
        if (s >= d - 1e-9) gh.leg++;
      }
      // Belt and braces: never inside a cabinet, whatever the route says.
      const q = W.resolve(gh.x, gh.z, world, RADIUS * 0.9);
      gh.x = q.x; gh.z = q.z;
      return gh.leg >= gh.path.length;
    }

    function step(dt) {
      dt = Math.max(0, Math.min(dt, 0.5));
      clock += dt;
      for (const gh of ghosts.slice()) {
        gh.alpha = Math.max(0, Math.min(1, gh.alpha + gh.fade * dt / FADE));
        if (gh.state === "walk") {
          if (reduced || move(gh, dt)) {
            Object.assign(gh, {x: gh.spot.x, z: gh.spot.z, state: "play", until: clock + between(r, PLAY),
              cabinet: gh.claim && gh.claim.endsWith("#0") ? gh.slug : null});
          }
        } else if (gh.state === "play") {
          let dy = gh.spot.yaw - gh.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
          gh.yaw += dy * Math.min(1, dt * 4);
          if (reduced) continue;  // they stay put
          const over = ghosts.filter((x) => x.state !== "leave").length > wanted();
          const stillBusy = levelOf(lv, gh.slug) > 0;
          if (clock >= gh.until || over || !stillBusy) {
            const o = !over && r() < AGAIN ? choose(gh.slug) : null;
            if (o) {
              claim(gh, o); gh.cabinet = null; gh.slug = o.c.slug; gh.spot = place(o.c, o.s, world);
              walkTo(gh, gh.spot, "walk");
            } else leave(gh);
          }
        } else if (gh.state === "leave") {
          if (reduced) { gh.fade = -1; }
          else {
            const done = move(gh, dt);
            const near = Math.hypot(gh.x - gh.goal.x, gh.z - gh.goal.z);
            if (near < 1.4) gh.fade = -1;
            if (done && gh.alpha <= 0) gh.gone = true;
          }
          if (gh.alpha <= 0 && gh.fade < 0) gh.gone = true;
        }
        if (gh.gone) ghosts.splice(ghosts.indexOf(gh), 1);
      }
      // Keep the number up: one arrival at a time, a few seconds apart.
      // The cap is hard: a ghost still on its way out counts against it.
      const active = ghosts.filter((x) => x.state !== "leave").length;
      if (active < wanted() && ghosts.length < cap && clock >= nextArrival) {
        spawn(reduced);
        nextArrival = clock + between(r, ARRIVE);
      }
      return people();
    }

    function people() {
      return ghosts.map((gh) => {
        const p = {id: gh.id, x: +gh.x.toFixed(3), z: +gh.z.toFixed(3), yaw: +gh.yaw.toFixed(3),
          color: COLOUR.slice(), alpha: +(ALPHA * gh.alpha).toFixed(3)};
        if (gh.state === "play" && gh.cabinet) p.cabinet = gh.cabinet;
        return p;
      });
    }

    return {
      step, people,
      setLevels(next) { lv = Object.assign({}, next || {}); },
      setCap(n) { cap = Math.max(0, n | 0); },
      setReduced(on) {
        reduced = !!on;
        if (reduced) for (const gh of ghosts) if (gh.state === "walk") Object.assign(gh, {x: gh.spot.x, z: gh.spot.z});
      },
      get count() { return ghosts.length; },
      get wanted() { return wanted(); },
      get ghosts() { return ghosts; },
      world, grid: g,
    };
  }

  /* ------------------------------------------------------------ page */
  const STEP_MS = 100;            // HallPeople eases between updates
  const REFRESH_MS = 30 * 60000;  // the levels change once a day

  function start(win) {
    win = win || root;
    const doc = win.document;
    let c = null, layout = null, levels = null, last = 0, wasOn = null;
    const phone = () => {
      try { return win.matchMedia("(pointer: coarse)").matches && Math.min(win.innerWidth, win.innerHeight) < 600; }
      catch (e) { return false; }
    };
    const feed = (list) => { if (win.HallPeople && typeof win.HallPeople.set === "function") win.HallPeople.set("ghosts", list); };
    async function fetchLevels() {
      try {
        const res = await win.fetch("/api/activity");
        if (!res.ok) return;
        const body = await res.json();
        if (body && body.levels && typeof body.levels === "object") {
          levels = body.levels;
          if (c) c.setLevels(levels);
        }
      } catch (e) { /* no ghosts: the hall is as it was */ }
    }
    function tick() {
      const hall = win.__hall;
      if (!hall || !hall.layout || !hall.kit || levels == null) return;
      const s = hall.settings || {};
      const on = s.ghosts !== false;
      if (!on || doc.hidden) {
        if (wasOn !== false) { feed([]); wasOn = false; c = null; }
        return;
      }
      const now = win.performance.now();
      const cap = budget({economy: !!(hall.state && hall.state.economy), phone: phone()});
      if (!c || layout !== hall.layout) {
        layout = hall.layout;
        // Seeded by the day, so two visitors' halls differ day to day but a reload looks alike.
        const seed = Math.floor(Date.now() / 864e5);
        c = crowd(layout, levels, {seed, cap, reduced: !!s.reducedMotion});
        last = now;
      }
      c.setCap(cap);
      c.setReduced(!!s.reducedMotion);
      const out = c.step((now - last) / 1000);
      last = now;
      wasOn = true;
      feed(out);
      if (hall.state) hall.state.ghosts = out.length;
    }
    fetchLevels();
    win.setInterval(fetchLevels, REFRESH_MS);
    win.setInterval(tick, STEP_MS);
    win.HallGhosts.running = true;
  }

  const HallGhosts = {rng, budget, target, grid, route, place, crowd, start,
    CAP, CAP_LOW, RADIUS, PLAY, ALPHA, COLOUR};
  if (typeof module !== "undefined" && module.exports) module.exports = HallGhosts;
  else {
    root.HallGhosts = HallGhosts;
    if (root.document) start(root);
  }
})(typeof window !== "undefined" ? window : globalThis);

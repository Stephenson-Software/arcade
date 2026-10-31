"use strict";
/* People in the hall: the figures other modules hand over, drawn by the hall
   engine. Nothing here is an obstacle: the visitor walks through figures.

   Three layers, each fed by its own module (RFC 0030):
     "presence"  live, opted-in players (hall-presence.js): solid little people
                 (a capsule, a head, two eyes: the engine's primitives, opaque
                 and lit) in a colour of their id, their display name above them
     "replays"   replayed walks          } translucent arcade ghosts (a dome, a
     "ghosts"    aggregate ghosts of play } scalloped hem, big eyes) in the colour given,
                                          hovering; meshes from a pool of 12 slots,
                                          built once and then only moved
                                          (hall3d/main.cpp hall_pose_meshes)
   A live person fading in or out (or too close to the eye) is drawn as a
   translucent copy of themselves, so they never pop.

     HallPeople.set(layer, people)    people: [{id, x, z, yaw, color: [r, g, b] 0..1,
                                       alpha 0..1, label?, cabinet?: slug}], at any rate.
                                       Each update is eased into over the layer's own
                                       update interval; a person left out fades away.
     HallPeople.clear(layer)          the same as set(layer, [])
     HallPeople.hide(layer, hidden)   hide or show a layer ("all": every layer)
     HallPeople.hidden(layer)         -> whether it is hidden
     HallPeople.layoutKey(slugs)      -> a stable key for a cabinet order (16 hex digits)
     HallPeople.colorOf(id)           -> [r, g, b] 0..1: a friendly colour of an id
     HallPeople.figure(layer, id)     -> {x, z, y, yaw, leaving, atCabinet} as drawn now, or null
     HallPeople.stats                 -> {drawn, layers: {presence, replays, ghosts}, labels}
     HallPeople.pick(view, nx, ny, px) -> {layer, id, dist} of the figure drawn under a screen
                                       point (nx, ny in -1..1, y up; px: the hit radius in CSS
                                       pixels), nearest first, or null
     HallPeople.reveal(layer, id)     a tap on a figure: its caption for a few seconds, beyond the
                                       labels' usual range and count (a live person's name; "A
                                       recent visitor" for a ghost, "A walk from today" for a replay)
     HallPeople.hover(hit)            the same while the mouse is over it (hit: pick()'s, or null)
     HallPeople.dots()                -> [{layer, id, x, z, color}]: everyone where they are now, for the
                                       map (hall.js drawMap); hidden layers and leavers left out
     HallPeople.frame(view)           -> hall.js, every frame: {items, points, builds, poses, changed}

   A person with a cabinet (a slug in this hall) stands beside that cabinet,
   facing it, a little to one side so the visitor's own view of its screen
   stays clear; others there stand further along. A moving figure faces the
   way it walks; one standing still turns to the yaw it was given.

   Budget (RFC 0030 §1): 12 figures, 6 on a phone or in economy, chosen
   presence first, then replays, then ghosts, nearest first. Detail drops
   with distance; nothing beyond 30 m is drawn. Labels: the nearest 6 (3 on
   a phone) within 14 m. Under reduced motion the figures neither bob nor
   sway; they still glide between updates.

   The maths is pure (HallPeople.crowd, tested under node in
   tests/browser/hall_people_test.cjs); the page part only adds the labels. */
(function (root) {
  const LAYERS = ["presence", "replays", "ghosts"];   // the budget's order
  const CAPSULE = 1, SPHERE = 3;                        // StrataRenderItem kinds
  const CAP = {full: 12, lite: 6};
  const LABELS = {full: 6, lite: 3}, LABEL_RANGE = 14;
  const NEAR = 9, MID = 18, FAR = 30;                  // metres: detail, simple, nothing beyond
  const FADE_IN = 0.5, FADE_OUT = 0.7;                  // seconds
  const SNAP = 6;                                       // metres: a longer jump is a teleport
  const MOVING = 0.15;                                  // m/s: faster than this faces where it goes
  const TURN = 7;                                       // 1/s: how quickly a figure turns
  const BESIDE = [0.75, -0.75, 1.3, -1.3, 1.85, -1.85]; // metres to the side of a cabinet
  const AT = 0.5;                                       // metres in front of a cabinet's face
  const LAYER_SPOT = {presence: 0, replays: 2, ghosts: 4};
  const MAX = 64;                                       // people per layer, at most
  const SLUG = /^[a-z][a-z0-9-]{0,40}$/;
  const EYE_COLOUR = [0.08, 0.06, 0.16];
  const MESH_SLOT = 3000;                               // hall.js mesh slots 3000..3011: figures as meshes
  // What a tap on a figure says: a live person's display name, else these (nothing about who).
  const CAPTION = {ghosts: "A recent visitor", replays: "A walk from today"};
  const REVEAL = 4;                                     // seconds a tapped figure's caption stays
  const TALL = {presence: 1.6, replays: 1.25, ghosts: 1.25}, WIDE = 0.32;  // metres, for picking

  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const num = (v, d) => (typeof v === "number" && Number.isFinite(v) ? v : d);

  /* ------------------------------------------------------------- keys */
  function fnv(str, seed) {
    let h = seed >>> 0;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }
  const hex = (n) => n.toString(16).padStart(8, "0");
  // The cabinet order of a hall, as a key: two people with the same key see
  // every cabinet in the same place.
  function layoutKey(slugs) {
    const s = (slugs || []).map(String).join("\n");
    return hex(fnv(s, 2166136261)) + hex(fnv(s, 0x9e3779b9));
  }
  // A bright, friendly colour from an id: its hue from a hash, never grey or dark.
  function colorOf(id) {
    const h = (fnv(String(id), 2166136261) % 360) / 360, s = 0.68, l = 0.6;
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const ch = (t) => {
      t = (t + 1) % 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    return [ch(h + 1 / 3), ch(h), ch(h - 1 / 3)].map((v) => Math.round(v * 1000) / 1000);
  }

  /* ----------------------------------------------------------- people */
  function clean(p) {
    if (!p || typeof p !== "object") return null;
    const id = typeof p.id === "string" || typeof p.id === "number" ? String(p.id).slice(0, 64) : "";
    if (!id || !Number.isFinite(p.x) || !Number.isFinite(p.z)) return null;
    const c = Array.isArray(p.color) && p.color.length >= 3 ? p.color.slice(0, 3).map((v) => clamp(num(v, 0.7), 0, 1)) : colorOf(id);
    const label = typeof p.label === "string" ? p.label.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 32) : "";
    return {id, x: p.x, z: p.z, yaw: num(p.yaw, 0), color: c, alpha: clamp(num(p.alpha, 1), 0, 1),
      label, cabinet: typeof p.cabinet === "string" && SLUG.test(p.cabinet) ? p.cabinet : null};
  }

  // The local frame of a cabinet (hall-walk.js frame()).
  function frameOf(c) {
    const a = c.angle || 0, r = [Math.cos(a), 0, -Math.sin(a)], f = [Math.sin(a), 0, Math.cos(a)];
    return {r, f, base: c.y || 0, p: (x, z) => [c.x + x * r[0] + z * f[0], c.z + x * r[2] + z * f[2]]};
  }
  // Where the k-th person at a cabinet stands: beside its front, facing it.
  function anchor(layout, slug, k) {
    const c = layout && layout.cabinets && layout.cabinets.find((x) => x.slug === slug);
    if (!c) return null;
    const fr = frameOf(c), depth = layout.cabinet && layout.cabinet.footprint ? layout.cabinet.footprint[3] : 0.72;
    const [x, z] = fr.p(BESIDE[k % BESIDE.length], depth + AT);
    return {x, z, y: fr.base, yaw: Math.atan2(fr.f[2], fr.f[0])};
  }

  /* --------------------------------------------------------- meshes */
  // {positions, normals, colors, uvs, indices}, built round the origin,
  // feet at y = 0, looking along -x (hall3d/main.cpp hall_pose_meshes turns it).
  function meshData() { return {positions: [], normals: [], colors: [], uvs: [], indices: []}; }
  // Turns a profile of [radius, y, normal radius, normal y] round the y axis.
  function lathe(m, profile, sides, colour, wave) {
    const base = m.positions.length / 3;
    for (let k = 0; k <= sides; k++) {
      const t = k / sides * 2 * Math.PI, ct = Math.cos(t), st = Math.sin(t);
      for (const [r, y, nr, ny, w] of profile) {
        const yy = y + (w && wave ? wave(t) * w : 0);
        m.positions.push(r * ct, yy, r * st);
        m.normals.push(nr * ct, ny, nr * st);
        m.colors.push(...colour);
      }
    }
    const n = profile.length;
    for (let k = 0; k < sides; k++) {
      for (let j = 0; j < n - 1; j++) {
        const a = base + k * n + j, b = base + (k + 1) * n + j;
        m.indices.push(a, a + 1, b + 1, a, b + 1, b);
      }
    }
  }
  function ball(m, cx, cy, cz, r, colour, rings = 5, sides = 8) {
    const profile = [];
    for (let i = 0; i <= rings; i++) {
      const th = Math.PI - i / rings * Math.PI;  // bottom to top
      profile.push([Math.sin(th) * r, Math.cos(th) * r, Math.sin(th), Math.cos(th)]);
    }
    const before = m.positions.length;
    lathe(m, profile, sides, colour);
    for (let i = before; i < m.positions.length; i += 3) { m.positions[i] += cx; m.positions[i + 1] += cy; m.positions[i + 2] += cz; }
  }
  // An arcade ghost: a dome, straight sides and a scalloped hem, with big eyes.
  function ghostMesh(colour) {
    const m = meshData(), R = 0.34, top = 0.86, profile = [];
    profile.push([R, 0.1, 1, 0, 1], [R, 0.45, 1, 0], [R, top, 1, 0]);
    for (let i = 1; i <= 5; i++) {
      const a = i / 5 * Math.PI / 2;
      profile.push([Math.cos(a) * R + (i === 5 ? 0 : 0), top + Math.sin(a) * R, Math.cos(a), Math.sin(a)]);
    }
    lathe(m, profile, 18, colour, (t) => 0.07 * Math.cos(t * 6));
    for (const k of [-1, 1]) {
      ball(m, -R * 0.82, 0.9, 0.13 * k, 0.09, [1, 1, 1], 4, 8);
      ball(m, -R * 0.82 - 0.07, 0.89, 0.13 * k, 0.045, [0.12, 0.18, 0.55], 3, 6);
    }
    return m;
  }
  // A person, as the solid one is drawn (capsule body, head, eyes), for fading.
  function personMesh(colour) {
    const m = meshData(), bright = colour.map((v) => 0.25 + 0.75 * v), body = bright.map((v) => v * 0.82);
    const profile = [], r = 0.25;
    for (let i = 0; i <= 4; i++) { const a = -Math.PI / 2 + i / 4 * Math.PI / 2; profile.push([Math.cos(a) * r, 0.4 + Math.sin(a) * r, Math.cos(a), Math.sin(a)]); }
    for (let i = 0; i <= 4; i++) { const a = i / 4 * Math.PI / 2; profile.push([Math.cos(a) * r, 0.84 + Math.sin(a) * r, Math.cos(a), Math.sin(a)]); }
    lathe(m, profile, 12, body);
    ball(m, 0, 1.31, 0, 0.22, bright, 6, 12);
    for (const k of [-1, 1]) ball(m, -0.19, 1.35, 0.085 * k, 0.04, EYE_COLOUR, 3, 6);
    return m;
  }

  function angleTo(from, to) {
    let d = (to - from) % (2 * Math.PI);
    if (d > Math.PI) d -= 2 * Math.PI;
    if (d < -Math.PI) d += 2 * Math.PI;
    return d;
  }

  /* A crowd: the figures of every layer, eased between updates. Times are seconds. */
  function crowd() {
    const figs = new Map();
    const layers = {};
    for (const l of LAYERS) layers[l] = {at: null, every: 1, hidden: false};
    let layout = null, lastFrame = null, drewSomething = false;
    let drawn = [];                       // the figures the last frame drew, for picking
    let tapped = null, hovered = null;    // {key, until}: captions asked for
    const stats = {drawn: 0, layers: {presence: 0, replays: 0, ghosts: 0}, labels: 0};

    function sample(f, now) {
      const u = f.dur > 0 ? clamp((now - f.t0) / f.dur, 0, 1) : 1;
      return {x: f.fx + (f.tx - f.fx) * u, z: f.fz + (f.tz - f.fz) * u, y: f.fy + (f.ty - f.fy) * u,
        vx: u < 1 ? (f.tx - f.fx) / f.dur : 0, vz: u < 1 ? (f.tz - f.fz) / f.dur : 0};
    }

    function set(layer, people, now) {
      const L = layers[layer];
      if (!L) return false;
      if (L.at != null) L.every = clamp(0.7 * L.every + 0.3 * (now - L.at), 0.05, 2);
      L.at = now;
      const list = (Array.isArray(people) ? people : []).map(clean).filter(Boolean).slice(0, MAX);
      // Who stands at each cabinet, in a fixed order, so they keep their spots.
      const at = {};
      for (const p of list.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
        if (!p.cabinet) continue;
        at[p.cabinet] = at[p.cabinet] || [];
        p.spot = LAYER_SPOT[layer] + at[p.cabinet].length;
        at[p.cabinet].push(p);
      }
      const seen = new Set();
      for (const p of list) {
        const key = layer + "\u0000" + p.id;
        if (seen.has(key)) continue;
        seen.add(key);
        const a = p.cabinet ? anchor(layout, p.cabinet, p.spot) : null;
        const to = a ? {x: a.x, z: a.z, y: a.y, yaw: a.yaw} : {x: p.x, z: p.z, y: 0, yaw: p.yaw};
        let f = figs.get(key);
        if (!f || f.leaving != null) {
          const phase = (fnv(p.id, 7) % 1000) / 1000 * 2 * Math.PI;
          f = {layer, id: p.id, born: f && f.leaving == null ? f.born : now, leaving: null, phase,
            fx: to.x, fz: to.z, fy: to.y, tx: to.x, tz: to.z, ty: to.y, t0: now, dur: 0, yaw: to.yaw};
          figs.set(key, f);
        } else {
          const s = sample(f, now);
          const jump = Math.hypot(to.x - s.x, to.z - s.z) > SNAP;
          Object.assign(f, {fx: jump ? to.x : s.x, fz: jump ? to.z : s.z, fy: jump ? to.y : s.y,
            tx: to.x, tz: to.z, ty: to.y, t0: now, dur: jump ? 0 : L.every * 1.05});
        }
        Object.assign(f, {goalYaw: to.yaw, color: p.color, alpha: p.alpha, label: layer === "presence" ? p.label : "",
          atCabinet: !!a});
      }
      for (const [key, f] of figs) if (f.layer === layer && !seen.has(key) && f.leaving == null) f.leaving = now;
      return true;
    }

    /* A live person, fully there: primitives (a capsule body, a sphere head
       and two dark eyes), opaque and lit, and a faint halo in their colour.
       items: kind, x, y, z, sx, sy, sz, r, g, b; points: x, y, z, px, diameter, r, g, b, a. */
    function solid(f, s, a, detail, bobY, items, points) {
      const c = f.color, x = s.x, z = s.z, y0 = s.y + bobY;
      const fx = -Math.cos(f.yaw), fz = -Math.sin(f.yaw), rx = -fz, rz = fx;
      // The head a touch brighter than the body, so the figure reads as round even unlit.
      const bright = c.map((v) => 0.25 + 0.75 * v), body = bright.map((v) => v * 0.82);
      items.push([CAPSULE, x, y0 + 0.62, z, 0.5, 0.47, 0.5, ...body]);
      items.push([SPHERE, x, y0 + 1.31, z, 0.44, 0.44, 0.44, ...bright]);
      if (detail >= 2) {
        for (const k of [-1, 1]) {
          items.push([SPHERE, x + fx * 0.19 + rx * 0.085 * k, y0 + 1.35, z + fz * 0.19 + rz * 0.085 * k,
            0.075, 0.09, 0.075, ...EYE_COLOUR]);
        }
      }
      if (detail >= 1) halo(points, x, y0 + 0.85, z, 1.5, c, 0.1 * a);
    }
    // A soft glow point, sent twice in a row: the kit's lowest tier draws only
    // every other soft point, and one of a pair always survives.
    function halo(points, x, y, z, d, c, al) { const r = [x, y, z, 0, d, ...c, al]; points.push(r, r.slice()); }

    /* Ghosts, replays, and a live person fading in or out (or at the eye):
       translucent meshes (ghostMesh, personMesh) from a pool of slots, built
       once per slot and colour and then only moved (hall_pose_meshes). */
    const pool = {slots: Array.from({length: CAP.full}, (_, i) => MESH_SLOT + i), of: new Map(), built: new Map(), used: new Set()};
    function meshSlot(key, shape, colour, builds) {
      let slot = pool.of.get(key);
      if (slot == null) {
        slot = pool.slots.find((k) => !pool.used.has(k));
        if (slot == null) return null;
        pool.of.set(key, slot);
      }
      pool.used.add(slot);
      const tag = shape + ":" + colour.map((v) => Math.round(v * 64)).join(",");
      if (pool.built.get(slot) !== tag) {
        pool.built.set(slot, tag);
        builds.push({slot, mesh: shape === "person" ? personMesh(colour) : ghostMesh(colour)});
      }
      return slot;
    }

    /* view: {x, y, z, yaw, pitch, fov, aspect} (the eye, hall.js view()), lite
       (a phone or economy), reduced (reduce motion), project (screen maths:
       HallControls.project). */
    function frame(view, now) {
      const dt = lastFrame == null ? 0 : clamp(now - lastFrame, 0, 0.25);
      lastFrame = now;
      const lite = !!view.lite, cap = lite ? CAP.lite : CAP.full;
      const live = [];
      for (const [key, f] of figs) {
        const fadeOut = f.leaving == null ? 1 : 1 - (now - f.leaving) / FADE_OUT;
        if (fadeOut <= 0) { figs.delete(key); continue; }
        const s = sample(f, now), speed = Math.hypot(s.vx, s.vz);
        const goal = speed > MOVING ? Math.atan2(-s.vz, -s.vx) : f.goalYaw;
        f.yaw += angleTo(f.yaw, goal) * (view.reduced ? 1 : 1 - Math.exp(-TURN * dt));
        if (layers[f.layer].hidden) continue;
        const d = Math.hypot(s.x - view.x, s.z - view.z);
        if (d > FAR) continue;
        const fadeIn = clamp((now - f.born) / FADE_IN, 0, 1);
        // Right at the eye a figure fades, so the view is never inside one.
        const close = clamp((d - 0.45) / 0.6, 0, 1);
        const a = f.alpha * fadeIn * fadeOut * close;
        if (a <= 0.01) continue;
        live.push({f, s, d, a, speed, rank: LAYERS.indexOf(f.layer)});
      }
      live.sort((p, q) => p.rank - q.rank || p.d - q.d);
      const shown = live.slice(0, cap);
      const items = [], points = [], labels = [], builds = [], poses = [];
      const counts = {presence: 0, replays: 0, ghosts: 0};
      const wasUsed = pool.used.size > 0;
      pool.used = new Set();
      const keep = new Set();
      drawn = [];
      const pinned = [tapped, hovered].filter((p) => p && p.until > now).map((p) => p.key);
      for (const {f, s, d, a, speed} of shown) {
        counts[f.layer]++;
        const key = f.layer + "\u0000" + f.id;
        let bobY = 0;
        if (!view.reduced) {
          bobY = speed > MOVING ? 0.045 * Math.abs(Math.sin(now * 8.5 + f.phase)) : 0.02 * Math.sin(now * 2.1 + f.phase);
        }
        const detail = d < NEAR ? 2 : d < MID ? 1 : 0;
        const lift = f.layer === "presence" ? bobY : 0.1 + (view.reduced ? 0 : 0.05 * Math.sin(now * 1.7 + f.phase));
        drawn.push({layer: f.layer, id: f.id, x: s.x, y: s.y + lift, z: s.z});
        if (pinned.includes(key)) {
          // Asked for (a tap, the mouse over it): shown whatever the distance or the count.
          const text = f.label || CAPTION[f.layer] || "";
          const p = text && view.project ? view.project(view, [s.x, s.y + lift + (f.layer === "presence" ? 1.78 : 1.45), s.z], 1.05) : null;
          if (p && p.on) labels.push({id: f.id, key, layer: f.layer, text, color: f.color, nx: p.nx, ny: p.ny, d, opacity: Math.max(a, 0.6), pinned: true});
        }
        if (f.layer === "presence" && a > 0.92) {
          solid(f, s, a, lite ? Math.min(detail, 1) + (d < 4 ? 1 : 0) : detail, bobY, items, points);
        } else {
          const person = f.layer === "presence";
          const slot = meshSlot(key, person ? "person" : "ghost", f.color, builds);
          if (slot != null) {
            keep.add(key);
            // Ghosts hover, and drift up and down more than people bob.
            const hover = person ? bobY : 0.1 + (view.reduced ? 0 : 0.05 * Math.sin(now * 1.7 + f.phase));
            poses.push([slot, s.x, s.y + hover, s.z, f.yaw, 1, Math.round(a * 32) / 32]);
            if (!person && detail >= 1) halo(points, s.x, s.y + hover + 0.7, s.z, 1.6, f.color, 0.08 * a);
          }
        }
        if (f.label && d < LABEL_RANGE && view.project && !pinned.includes(key)) {
          const p = view.project(view, [s.x, s.y + bobY + 1.78, s.z], 1.05);
          if (p.on) labels.push({id: f.id, key, text: f.label, color: f.color, nx: p.nx, ny: p.ny, d,
            opacity: a * clamp((LABEL_RANGE - d) / 4, 0, 1)});
        }
      }
      for (const k of [...pool.of.keys()]) if (!keep.has(k)) pool.of.delete(k);
      // Every slot that was ever built is posed each time, an unused one at alpha 0 (taken out).
      for (const slot of pool.built.keys()) if (!pool.used.has(slot)) poses.push([slot, 0, -10, 0, 0, 1, 0]);
      const meshesChanged = pool.used.size > 0 || wasUsed;
      // Nearest first, at most six (three on a phone); one asked for always, beyond that.
      labels.sort((p, q) => p.d - q.d);
      const usual = labels.filter((l) => !l.pinned).slice(0, lite ? LABELS.lite : LABELS.full);
      labels.splice(0, labels.length, ...labels.filter((l) => l.pinned || usual.includes(l)));
      stats.drawn = shown.length;
      stats.layers = counts;
      stats.labels = labels.length;
      const changed = shown.length > 0 || drewSomething;
      drewSomething = shown.length > 0;
      return {items, points, labels, changed, builds, poses: meshesChanged ? poses : []};
    }

    return {
      set, frame, stats,
      setLayout(l) { layout = l || null; },
      hide(layer, on) {
        for (const l of layer === "all" ? LAYERS : [layer]) if (layers[l]) layers[l].hidden = !!on;
      },
      hidden: (layer) => !!(layers[layer] && layers[layer].hidden),
      /* The figure drawn under a screen point, by the last frame's figures:
         each a column from its feet to the top of its head, as wide as it
         is (at least px either side). view as frame()'s, with height (CSS
         pixels) and project. The nearest one hit wins. */
      pick(view, nx, ny, px) { return pickFigure(drawn, view, nx, ny, px); },
      reveal(layer, id, now) { tapped = {key: layer + "\u0000" + id, until: now + REVEAL}; },
      hover(hit, now) { hovered = hit ? {key: hit.layer + "\u0000" + hit.id, until: Infinity} : null; },
      // Every figure of a shown layer, wherever it is (the map shows the whole hall), live people first.
      dots(now) {
        const out = [];
        for (const f of figs.values()) {
          if (f.leaving != null || layers[f.layer].hidden) continue;
          const s = sample(f, now);
          out.push({layer: f.layer, id: f.id, x: s.x, z: s.z, color: f.color});
        }
        return out.sort((p, q) => LAYERS.indexOf(q.layer) - LAYERS.indexOf(p.layer));
      },
      get revealed() {
        const t = lastFrame == null ? 0 : lastFrame;
        return [tapped, hovered].filter((p) => p && p.until > t).map((p) => p.key.replace("\u0000", ":"));
      },
      get size() { return figs.size; },
      figure(layer, id, now) {
        const f = figs.get(layer + "\u0000" + id);
        if (!f) return null;
        const s = sample(f, now);
        return {x: s.x, z: s.z, y: s.y, yaw: f.yaw, leaving: f.leaving != null, atCabinet: f.atCabinet};
      },
    };
  }

  /* drawn: [{layer, id, x, y, z}] (y: the feet); see crowd().pick. */
  function pickFigure(drawn, view, nx, ny, px) {
    if (!view || !view.project || !drawn || !drawn.length) return null;
    const h = view.height || 600, w = h * (view.aspect || 1), t = Math.tan((view.fov || 62) * Math.PI / 360);
    const sx = (nx + 1) / 2 * w, sy = (1 - ny) / 2 * h;
    const cp = Math.cos(view.pitch || 0), f = [-cp * Math.cos(view.yaw), -Math.sin(view.pitch || 0), -cp * Math.sin(view.yaw)];
    let best = null;
    for (const g of drawn) {
      const tall = TALL[g.layer] || 1.5, mid = [g.x - view.x, g.y + tall / 2 - view.y, g.z - view.z];
      const depth = mid[0] * f[0] + mid[1] * f[1] + mid[2] * f[2];
      if (depth < 0.3) continue;
      const a = view.project(view, [g.x, g.y, g.z], 50), b = view.project(view, [g.x, g.y + tall, g.z], 50);
      if (!a.on || !b.on) continue;
      const ax = (a.nx + 1) / 2 * w, ay = (1 - a.ny) / 2 * h, bx = (b.nx + 1) / 2 * w, by = (1 - b.ny) / 2 * h;
      // Distance from the point to the column's axis, on screen.
      const vx = bx - ax, vy = by - ay, l2 = vx * vx + vy * vy || 1;
      const u = clamp(((sx - ax) * vx + (sy - ay) * vy) / l2, 0, 1);
      const off = Math.hypot(sx - (ax + vx * u), sy - (ay + vy * u));
      const half = WIDE / (depth * t) * h / 2;
      if (off > Math.max(half, px || 0)) continue;
      const dist = Math.hypot(mid[0], mid[1], mid[2]);
      if (!best || dist < best.dist) best = {layer: g.layer, id: g.id, dist};
    }
    return best;
  }

  const pure = {crowd, pickFigure, CAPTION, layoutKey, colorOf, anchor, clean, ghostMesh, personMesh, LAYERS, CAP, LABELS, FAR, MESH_SLOT};
  if (typeof module !== "undefined" && module.exports) { module.exports = pure; return; }

  /* ------------------------------------------------------- the page */
  const crowdNow = crowd();
  const clock = () => performance.now() / 1000;
  let box = null;
  const tags = new Map();

  function syncLayout() {
    const l = root.__hall && root.__hall.layout;
    if (l) crowdNow.setLayout(l);
  }

  function showLabels(labels, view) {
    if (!box) {
      if (!labels.length) return;
      box = document.createElement("div");
      box.id = "people-labels";
      box.setAttribute("aria-hidden", "true");
      document.body.appendChild(box);
    }
    const w = view.width, h = view.height, keep = new Set(), placed = [];
    for (const l of labels) {
      const k = l.key || l.id;
      keep.add(k);
      let t = tags.get(k);
      if (!t) {
        t = document.createElement("span");
        t.className = "person-label";
        box.appendChild(t);
        tags.set(k, t);
      }
      if (t.textContent !== l.text) t.textContent = l.text;
      t.classList.toggle("anon", !!l.layer && l.layer !== "presence");
      t.style.setProperty("--who", `rgb(${l.color.map((v) => Math.round(v * 255)).join(",")})`);
      // Nearest first; a farther name that would cover a nearer one steps up above it.
      const x = (l.nx + 1) / 2 * w, lw = t.offsetWidth || 60, lh = (t.offsetHeight || 22) + 2;
      let y = (1 - l.ny) / 2 * h;
      for (let k = 0; k < 4; k++) {
        const hit = placed.find((p) => Math.abs(p.x - x) < (p.w + lw) / 2 && Math.abs(p.y - y) < lh);
        if (!hit) break;
        y = hit.y - lh;
      }
      placed.push({x, y, w: lw});
      t.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
      t.style.opacity = l.opacity.toFixed(2);
    }
    for (const [id, t] of tags) if (!keep.has(id)) { t.remove(); tags.delete(id); }
  }

  root.HallPeople = {
    set(layer, people) { syncLayout(); return crowdNow.set(layer, people, clock()); },
    clear(layer) { return crowdNow.set(layer, [], clock()); },
    hide(layer, hidden) { crowdNow.hide(layer, hidden); },
    hidden: (layer) => crowdNow.hidden(layer),
    layoutKey, colorOf,
    get stats() { return JSON.parse(JSON.stringify(crowdNow.stats)); },
    figure: (layer, id) => crowdNow.figure(layer, id, clock()),
    pick(view, nx, ny, px) {
      return crowdNow.pick(Object.assign({project: root.HallControls && root.HallControls.project}, view), nx, ny, px);
    },
    reveal(layer, id) { crowdNow.reveal(layer, id, clock()); },
    hover(hit) { crowdNow.hover(hit || null, clock()); },
    get revealed() { return crowdNow.revealed; },
    dots: () => crowdNow.dots(clock()),
    frame(view) {
      if (view.layout) crowdNow.setLayout(view.layout);
      const out = crowdNow.frame(Object.assign({project: root.HallControls && root.HallControls.project}, view), clock());
      showLabels(out.labels, view);
      return out;
    },
  };
})(typeof window !== "undefined" ? window : globalThis);

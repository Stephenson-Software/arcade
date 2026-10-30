"use strict";
/* The walkable arcade hall: https://play.<base>/hall/

   The layout (which cabinet stands where, its colours and parts) comes from
   layout.json, which arcade builds from the registry with src/arcade/hall.py,
   the same code that draws the README picture. This file turns it into
   Strata meshes and textures (hall3d/main.cpp keeps and draws them), and
   walks the visitor round it (hall-walk.js does the maths).

   Playing a game: walking up to a cabinet shows its name and "Press E / tap
   to play". The game opens in a full-screen frame over the hall with a "Back
   to the hall" button, which returns to the same spot. A frame needs the
   hall's own cross-origin isolation to match the game's (a tak or Roam build
   needs an isolated parent; a game without COOP/COEP cannot be framed by
   one), so when they differ the hall reloads itself in the other mode, with
   the game open (?isolated=1&play=<slug>), and the visitor's place kept in
   the URL hash. When framing is off (layout.embed false) or impossible, the
   game opens as a page of its own; the browser's Back button returns here,
   to the same spot, and /hall/?at=<slug> starts in front of any cabinet. */
(function () {
  const W = window.HallWalk;
  const $ = (id) => document.getElementById(id);
  const canvas = $("hall");
  const params = new URLSearchParams(location.search);
  const touchFirst = matchMedia("(hover: none), (pointer: coarse)").matches;
  const POS_KEY = "arcade-hall.pos";
  const TEX_MIPS = 1, TEX_CLAMP = 2 | 4;
  const SCREEN_TEX = [512, 288], MARQUEE_TEX = [512, 112];

  const session = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private window, blocked storage */ } },
  };

  let layout = null, world = null, mod = null, kit = null;
  let me = null, near = null, target = null, playing = null;
  const state = {posters: 0, posterErrors: 0, frames: 0, mode: self.crossOriginIsolated ? "isolated" : "plain"};

  /* --------------------------------------------------------- the heap */
  function heap() { return new Uint8Array(mod.HEAPF32.buffer); }
  function put(typed) {
    const bytes = new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength);
    const ptr = mod._malloc(Math.max(bytes.length, 4));
    heap().set(bytes, ptr);
    return ptr;
  }
  function call(fn, arrays, ...rest) {
    const ptrs = arrays.map((a) => (a ? put(a) : 0));
    try { return fn(...ptrs, ...rest); } finally { ptrs.forEach((p) => p && mod._free(p)); }
  }
  function texture(slot, w, h, rgba, flags) {
    const ptr = put(rgba);
    try { return mod._hall_texture(slot, w, h, ptr, flags); } finally { mod._free(ptr); }
  }
  function mesh(slot, mb, textureSlot = -1, flags = 0) {
    const p = put(new Float32Array(mb.positions)), n = put(new Float32Array(mb.normals));
    const c = put(new Float32Array(mb.colors)), u = mb.uvs.length ? put(new Float32Array(mb.uvs)) : 0;
    const i = put(new Uint32Array(mb.indices));
    try {
      return mod._hall_mesh(slot, p, n, c, u, mb.positions.length / 3, i, mb.indices.length, textureSlot, flags);
    } finally { [p, n, c, u, i].forEach((x) => x && mod._free(x)); }
  }
  function rows(fn, list) {
    const flat = new Float32Array(list.flat());
    call((ptr) => fn(ptr, list.length), [flat]);
  }

  /* ------------------------------------------------- meshes (hall.py) */
  class MeshBuilder {
    constructor() { this.positions = []; this.normals = []; this.colors = []; this.uvs = []; this.indices = []; }
    // Corners counter-clockwise seen from the side the normal points to, from bottom-left.
    quad(corners, normal, colour = [1, 1, 1], uvs = [[0, 1], [1, 1], [1, 0], [0, 0]]) {
      const base = this.positions.length / 3;
      corners.forEach((c, k) => {
        this.positions.push(...c); this.normals.push(...normal); this.colors.push(...colour); this.uvs.push(...uvs[k]);
      });
      this.indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
    box(fr, lo, hi, colour) {
      const [x0, y0, z0] = lo, [x1, y1, z1] = hi;
      const faces = [
        [[0, 0, 1], [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]],
        [[0, 0, -1], [[x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0]]],
        [[1, 0, 0], [[x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1]]],
        [[-1, 0, 0], [[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]]],
        [[0, 1, 0], [[x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0]]],
        [[0, -1, 0], [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]]],
      ];
      for (const [n, cs] of faces) this.quad(cs.map((c) => fr.p(...c)), fr.n(...n), colour);
    }
  }

  /* --------------------------------------------- textures (hall.py too) */
  const rgb255 = (c, k = 255) => c.map((v) => Math.round(k * v));
  function canvas2d(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    return [c, c.getContext("2d", {willReadFrequently: true})];
  }
  function fitFont(ctx, text, boxW, start, floor = 14) {
    for (let size = start; size > floor; size -= 2) {
      ctx.font = `bold ${size}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
      if (ctx.measureText(text).width <= boxW) return;
    }
    ctx.font = `bold ${floor}px "DejaVu Sans", Verdana, system-ui, sans-serif`;
  }
  function pixels(ctx, w, h) { return new Uint8Array(ctx.getImageData(0, 0, w, h).data.buffer); }
  function titleCard(c) {
    const [w, h] = SCREEN_TEX, [, ctx] = canvas2d(w, h);
    ctx.fillStyle = `rgb(${rgb255(c.colour, 40)})`; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = `rgb(${rgb255(c.colour, 22)})`;
    for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);
    fitFont(ctx, c.title, w - 60, 64);
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(c.title, w / 2, h / 2);
    if (!c.deployed) {
      ctx.font = `bold 22px system-ui, sans-serif`; ctx.fillStyle = "rgba(255,255,255,.7)";
      ctx.fillText("COMING SOON", w / 2, h - 40);
    }
    return pixels(ctx, w, h);
  }
  function marquee(c) {
    const [w, h] = MARQUEE_TEX, [, ctx] = canvas2d(w, h);
    ctx.fillStyle = "rgb(12,10,18)"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = `rgb(${rgb255(c.colour)})`; ctx.lineWidth = 4; ctx.strokeRect(5, 5, w - 10, h - 10);
    const text = c.title.toUpperCase();
    fitFont(ctx, text, w - 48, 62);
    ctx.fillStyle = `rgb(${c.colour.map((v) => Math.round(255 * (0.55 + 0.45 * v)))})`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, w / 2, h / 2 + 2);
    return pixels(ctx, w, h);
  }
  // The light a screen casts: its mean colour, lifted (make_hall_media.py build()).
  function glowOf(rgba) {
    const sum = [0, 0, 0];
    for (let k = 0; k < rgba.length; k += 4 * 7) { sum[0] += rgba[k]; sum[1] += rgba[k + 1]; sum[2] += rgba[k + 2]; }
    const n = rgba.length / (4 * 7), avg = sum.map((v) => v / n / 255), lift = Math.max(Math.max(...avg), 0.2);
    return avg.map((v) => Math.min(1, 0.25 + 0.75 * v / lift));
  }

  /* ------------------------------------------------------ the scene */
  const screenSlot = (i) => 100 + i, marqueeSlot = (i) => 400 + i;
  let scenePoints = null;
  // A cabinet's screen, at a brightness (its vertex colour: the attract-mode shimmer).
  function screenQuad(c, i, b) {
    const [x0, y0, x1, y1, z] = layout.cabinet.screen, fr = c.fr, q = new MeshBuilder();
    q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1), [b, b, b]);
    mesh(screenSlot(i), q, screenSlot(i), 1 /* STRATA_MESH_UNLIT */);
  }

  /* Attract mode (hall-life.js): now and then a screen shows its game's title
     card instead of its poster, the nearest screens shimmer faintly and the
     marquees' glow breathes. Nothing moves under reduced motion. */
  const LIFE_STEP = 1 / 12;
  let lifeAt = -1, attractIdx = -1;
  function life(t) {
    if (reducedMotion || !scenePoints || t - lifeAt < LIFE_STEP) return;
    lifeAt = t;
    const cs = layout.cabinets;
    let k = HallLife.attract(t, cs.length);
    if (k >= 0 && (!cs[k].posterPx || cs[k] === near || cs[k] === playing)) k = -1;
    if (k !== attractIdx) {
      if (attractIdx >= 0 && cs[attractIdx].posterPx) texture(screenSlot(attractIdx), SCREEN_TEX[0], SCREEN_TEX[1], cs[attractIdx].posterPx, TEX_MIPS | TEX_CLAMP);
      if (k >= 0) texture(screenSlot(k), SCREEN_TEX[0], SCREEN_TEX[1], cs[k].titlePx, TEX_MIPS | TEX_CLAMP);
      attractIdx = k;
      state.attract = k >= 0 ? cs[k].slug : null;
    }
    cs.forEach((c, i) => {
      if (me && Math.hypot(c.x - me.x, c.z - me.z) < 8) screenQuad(c, i, HallLife.flicker(t, i));
      scenePoints[c.glowPoint][8] = 0.16 * HallLife.pulse(t, i);
    });
    rows(mod._hall_set_points, scenePoints);
  }
  function buildScene() {
    const body = new MeshBuilder();
    const cab = layout.cabinet, items = [], points = [];
    layout.cabinets.forEach((c, i) => {
      const fr = W.frame(c);
      c.fr = fr;
      const roles = {body: cab.body, trim: cab.trim, bezel: cab.bezel, side: c.colour.map((v) => v * cab.sideShade)};
      for (const [lo, hi, role] of cab.boxes) body.box(fr, lo, hi, roles[role]);
      // Joystick and buttons, as Strata primitives (make_hall_media.py controls()).
      const P = (x, y, z) => fr.p(x, y, z);
      items.push([2, ...P(-0.22, 1.11, 0.53), 0.025, 0.10, 0.025, 0.1, 0.1, 0.1]);
      items.push([3, ...P(-0.22, 1.17, 0.53), 0.07, 0.07, 0.07, 0.85, 0.12, 0.12]);
      [[0.95, 0.85, 0.2], c.colour, [0.25, 0.75, 0.35]].forEach((col, k) =>
        items.push([2, ...P(0.04 + 0.12 * k, 1.07, 0.52 - 0.03 * k), 0.07, 0.025, 0.07, ...col]));
      c.glowPoint = points.length;
      points.push([...P(0, 2.15, 0.45), 0, 1.3, ...c.colour.map((v) => 0.4 + 0.6 * v), 0.16]);
      c.glow = c.colour.map((v) => 0.35 + 0.65 * v);
      c.titlePx = titleCard(c);
      texture(screenSlot(i), SCREEN_TEX[0], SCREEN_TEX[1], c.titlePx, TEX_MIPS | TEX_CLAMP);
      texture(marqueeSlot(i), MARQUEE_TEX[0], MARQUEE_TEX[1], marquee(c), TEX_MIPS | TEX_CLAMP);
      screenQuad(c, i, 1);
      const [x0, y0, x1, y1, z] = cab.marquee, q = new MeshBuilder();
      q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1));
      mesh(marqueeSlot(i), q, marqueeSlot(i), 1 /* STRATA_MESH_UNLIT */);
    });
    scenePoints = points;
    mesh(0, body);
    buildRoom(points);
    rows(mod._hall_set_items, items);
    rows(mod._hall_set_points, points);
    mod._hall_set_view(layout.room.style ? layout.room.style.ambient : 0.32, W.FOV);
    setLights();
  }

  /* The room: walls, carpet, ceiling, and the props hall.py lists (the stage,
     the counter, the ceiling panels), all plain boxes, and its signs. */
  function buildRoom(points) {
    const room = layout.room, st = room.style, w = room.halfWidth, near = room.near, far = room.far, h = room.height;
    const flat = {p: (x, y, z) => [x, y, z], n: (x, y, z) => [x, y, z]};
    const floor = new MeshBuilder(), reps = [2 * w / CARPET_TILE, (near - far) / CARPET_TILE];
    floor.quad([[-w, 0, near], [w, 0, near], [w, 0, far], [-w, 0, far]], [0, 1, 0], [1, 1, 1],
      [[0, reps[1]], [reps[0], reps[1]], [reps[0], 0], [0, 0]]);
    texture(1, 256, 256, carpet(st), TEX_MIPS);
    mesh(1, floor, 1);
    const walls = new MeshBuilder(), lit = new MeshBuilder();
    const [d0, d1] = room.door;
    // Each wall: the lower wainscot and the wall above it.
    const wall = (a, b, n) => {
      walls.quad([[a[0], 0, a[1]], [b[0], 0, b[1]], [b[0], 1.1, b[1]], [a[0], 1.1, a[1]]], n, st.wainscot);
      walls.quad([[a[0], 1.1, a[1]], [b[0], 1.1, b[1]], [b[0], h, b[1]], [a[0], h, a[1]]], n, st.wall);
    };
    wall([-w, far], [w, far], [0, 0, 1]);
    wall([-w, near], [-w, far], [1, 0, 0]);
    wall([w, far], [w, near], [-1, 0, 0]);
    wall([w, near], [-w, near], [0, 0, -1]);
    walls.quad([[-w, h, far], [w, h, far], [w, h, near], [-w, h, near]], [0, -1, 0], st.ceiling);
    for (const b of room.props) (b.unlit ? lit : walls).box(flat, b.lo, b.hi, b.colour);
    mesh(2, walls);
    mesh(3, lit, -1, 1 /* STRATA_MESH_UNLIT */);
    room.signs.forEach((sg, i) => {
      const slot = signSlot(i), tw = 512, th = Math.round(512 * sg.h / sg.w);
      texture(slot, tw, th, signTexture(sg, tw, th), TEX_MIPS | TEX_CLAMP);
      const q = new MeshBuilder(), x0 = sg.x - sg.w / 2 * sg.facing, x1 = sg.x + sg.w / 2 * sg.facing;
      const y0 = sg.y - sg.h / 2, y1 = sg.y + sg.h / 2;
      q.quad([[x0, y0, sg.z], [x1, y0, sg.z], [x1, y1, sg.z], [x0, y1, sg.z]], [0, 0, sg.facing]);
      mesh(slot, q, slot, 1);
      points.push([sg.x, sg.y, sg.z + 0.15 * sg.facing, 0, sg.w * 0.9, ...sg.colour, 0.10]);
    });
    // A soft pool under each lit ceiling panel's light.
    for (const l of room.lights.slice(2)) points.push([l[0], l[1] + 0.4, l[2], 0, 1.5, ...st.panel, 0.18]);
  }
  const signSlot = (i) => 700 + i, CARPET_TILE = 1.6;
  function carpet(st) {
    const size = 256, [, ctx] = canvas2d(size, size);
    ctx.fillStyle = `rgb(${rgb255(st.carpet)})`; ctx.fillRect(0, 0, size, size);
    for (const [x, y, r, k] of st.dots) {
      ctx.fillStyle = `rgb(${rgb255(st.carpetDots[k])})`;
      // Wrapped, so the tile repeats without seams.
      for (const ox of [-size, 0, size]) for (const oy of [-size, 0, size]) {
        ctx.beginPath(); ctx.arc(x + ox, y + oy, r, 0, 2 * Math.PI); ctx.fill();
      }
    }
    return pixels(ctx, size, size);
  }
  function signTexture(sg, w, h) {
    const [, ctx] = canvas2d(w, h);
    ctx.fillStyle = "rgb(20,12,18)"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = `rgb(${rgb255(sg.colour)})`; ctx.lineWidth = 5; ctx.strokeRect(6, 6, w - 12, h - 12);
    fitFont(ctx, sg.text, w - 56, Math.round(h * 0.62));
    ctx.fillStyle = `rgb(${sg.colour.map((v) => Math.round(255 * (0.6 + 0.4 * v)))})`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(sg.text, w / 2, h / 2 + 2);
    return pixels(ctx, w, h);
  }
  function setLights() {
    const lights = layout.room.lights.slice();
    for (const c of layout.cabinets) lights.push([...c.fr.p(0, 1.5, 1.0), 2.6, ...c.glow, 1.2]);
    rows(mod._hall_set_lights, lights);
  }

  /* ---------------------------------------- posters, nearest first */
  const posterQueue = [];
  let posterBusy = 0;
  function queuePosters() {
    layout.cabinets.forEach((c, i) => { if (c.poster) posterQueue.push(i); });
    pumpPosters();
  }
  function pumpPosters() {
    while (posterBusy < 2 && posterQueue.length) {
      // Nearest to the visitor next.
      let best = 0, bestD = Infinity;
      posterQueue.forEach((i, k) => {
        const c = layout.cabinets[i], d = me ? Math.hypot(c.x - me.x, c.z - me.z) : 0;
        if (d < bestD) { bestD = d; best = k; }
      });
      const i = posterQueue.splice(best, 1)[0];
      posterBusy++;
      loadPoster(i).finally(() => { posterBusy--; pumpPosters(); });
    }
  }
  function loadPoster(i) {
    const c = layout.cabinets[i];
    return new Promise((resolve) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => {
        try {
          const [w, h] = SCREEN_TEX, [, ctx] = canvas2d(w, h);
          const s = Math.max(w / img.naturalWidth, h / img.naturalHeight);
          const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
          ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
          const px = HallLife.scanlines(pixels(ctx, w, h), w, h);
          c.posterPx = px;
          if (i !== attractIdx) texture(screenSlot(i), w, h, px, TEX_MIPS | TEX_CLAMP);
          c.glow = glowOf(px);
          setLights();
          state.posters++;
        } catch (e) { state.posterErrors++; }
        resolve();
      };
      img.onerror = () => { state.posterErrors++; resolve(); };
      img.src = c.poster;
    });
  }

  /* ------------------------------------------------- where you stand */
  function savePlace() {
    if (!me) return;
    const v = `${me.x.toFixed(2)},${me.z.toFixed(2)},${me.yaw.toFixed(3)},${me.pitch.toFixed(3)}`;
    session.set(POS_KEY, v);
    const url = new URL(location.href);
    url.hash = "p=" + v;
    url.searchParams.delete("at");
    url.searchParams.delete("play");
    if (url.href !== location.href) history.replaceState(history.state, "", url.href);
  }
  function parsePlace(s) {
    const m = /^(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)(?:,(-?[\d.]+))?$/.exec(s || "");
    if (!m) return null;
    const p = {x: +m[1], z: +m[2], yaw: +m[3], pitch: m[4] != null ? +m[4] : 0.06};
    return [p.x, p.z, p.yaw, p.pitch].every(Number.isFinite) ? p : null;
  }
  function startPlace() {
    const at = params.get("at") || params.get("play");
    const c = at && layout.cabinets.find((k) => k.slug === at);
    const hash = location.hash.startsWith("#p=") ? parsePlace(location.hash.slice(3)) : null;
    // ?play= keeps the place the visitor played from (in the hash), to step back out to.
    if (c && !(params.get("play") && hash)) { const f = W.front(c, standOff()); return {x: f.x, z: f.z, yaw: f.yaw, pitch: 0.12}; }
    const saved = hash || parsePlace(session.get(POS_KEY));
    // A place saved under an older layout may be inside a cabinet now: the nearest walkway.
    if (saved) return Object.assign(saved, W.settle(saved.x, saved.z, world));
    return W.spawn(layout);
  }

  /* --------------------------------------------------------- playing */
  function canFrame(c) {
    if (!layout.embed) return "navigate";
    const iso = !!self.crossOriginIsolated;
    if (c.isolation === iso) return "frame";
    return layout.modes ? "switch" : "navigate";
  }
  /* The move into a game and back out (hall-play.js): the camera eases to
     square-on at the cabinet's screen while the game loads hidden behind it,
     the game crossfades in once it has painted, and Back reverses it. */
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SETTLE_MS = 450;  // after the frame's load event, for the game's first paint
  let tr = null, clock = 0, frameToken = 0, standAt = null;
  // The machine's clock: the frame's time when frames are driven by a tool
  // (?drive=1), else the page's (the loop rests while a game is shown).
  const nowMs = () => (kit && kit.driven ? clock : performance.now());
  const standPose = () => ({x: me.x, y: W.EYE, z: me.z, yaw: kit.cam.yaw, pitch: kit.cam.pitch});
  const screenPose = (c) => HallPlay.screenPose(c.fr, layout.cabinet.screen,
    canvas.clientWidth / Math.max(canvas.clientHeight, 1), W.FOV);
  function switchUrl(c) {
    const url = new URL(location.href);
    url.search = "";
    if (c.isolation) url.searchParams.set("isolated", "1");
    url.searchParams.set("play", c.slug);
    return url.href;
  }
  function play(c) {
    if (!c || !c.deployed || !c.url || !tr || tr.state !== "idle") return;
    savePlace();
    const how = canFrame(c);
    state.lastPlay = {slug: c.slug, how};
    playing = c;
    keys.clear(); stickIn = {forward: 0, right: 0, run: false}; target = null;
    if (document.pointerLockElement) document.exitPointerLock();
    dressPlayer(c);
    standAt = standPose();
    tr.start(nowMs(), {from: standAt, to: screenPose(c), how});
    document.body.classList.add("moving");
  }
  // The overlay, until the game paints: the cabinet's poster over a dark
  // tone of its colour, never a blank white or black.
  function dressPlayer(c) {
    $("player-title").textContent = c.title;
    $("player-open").href = c.url;
    const tone = (c.glow || c.colour).map((v) => Math.round(255 * (0.06 + 0.12 * v)));
    const el = $("player");
    el.style.backgroundColor = `rgb(${tone})`;
    el.style.backgroundImage = c.poster ? `url("${c.poster}")` : "none";
    $("fade").style.backgroundColor = `rgb(${tone})`;
  }
  function loadFrame(c) {
    const token = ++frameToken, fr = $("player-frame"), el = $("player");
    el.style.opacity = "0";
    el.hidden = false;
    el.classList.add("loading");
    fr.onload = () => {
      if (token !== frameToken || fr.src === "about:blank") return;
      setTimeout(() => { if (token === frameToken && tr) tr.loaded(nowMs()); }, SETTLE_MS);
    };
    fr.src = c.url;
  }
  function unloadFrame() {
    frameToken++;
    const el = $("player");
    el.hidden = true;
    el.classList.remove("loading");
    el.style.opacity = "0";
    $("player-frame").src = "about:blank";
    document.body.classList.remove("playing");
  }
  // One frame of the move: the camera, the overlays and what happened.
  function stepPlay(now) {
    clock = now;
    const u = tr.update(now);
    for (const e of u.events) {
      if (e === "load-frame") loadFrame(playing);
      else if (e === "frame-shown") {
        $("player").classList.remove("loading");
        $("player").style.opacity = "1";
        document.body.classList.add("playing");
        document.body.classList.remove("moving");
        $("back").focus();
        kit.running = false;  // the hall rests under the game
        hum.pause(true);
        state.lastShown = playing.slug;
      } else if (e === "unload-frame") unloadFrame();
      else if (e === "navigate") location.assign(playing.url);
      else if (e === "switch") location.assign(switchUrl(playing));
      else if (e === "idle") {
        state.lastBack = playing ? playing.slug : null;
        hum.pause(document.hidden);
        playing = null;
        document.body.classList.remove("moving");
        if (standAt) Object.assign(kit.cam, {yaw: standAt.yaw, pitch: standAt.pitch, tx: standAt.x, ty: standAt.y, tz: standAt.z});
        canvas.focus({preventScroll: true});
      }
    }
    if (u.state !== "idle" && u.state !== "playing") {
      $("player").style.opacity = String(u.frame);
    }
    $("fade").style.opacity = String(u.fade);
    $("fade").hidden = u.fade <= 0;
    state.move = u.state;
    return u;
  }
  function closeFrame() {
    if (!playing || !tr) return;
    $("player").style.opacity = "1";
    document.body.classList.remove("playing");
    document.body.classList.add("moving");
    lastNow = 0;
    kit.start();
    tr.back(nowMs());
  }
  $("back").addEventListener("click", closeFrame);

  /* The hall's sound: off until asked for, remembered, quiet while a game plays. */
  const SOUND_KEY = "arcade-hall.sound", hum = HallLife.hum(), soundBtn = $("sound");
  function showSound() {
    soundBtn.setAttribute("aria-pressed", String(hum.on));
    soundBtn.textContent = hum.on ? "Sound on" : "Sound off";
  }
  soundBtn.addEventListener("click", () => {
    hum.set(!hum.on);
    StrataKit.store.set(SOUND_KEY, hum.on ? "1" : "0");
    showSound();
    canvas.focus({preventScroll: true});
  });
  // A remembered "on" still waits for a tap: browsers start sound only on one.
  if (StrataKit.store.get(SOUND_KEY) === "1") {
    const first = () => { if (!hum.on) { hum.set(true); showSound(); } };
    window.addEventListener("pointerdown", first, {once: true, capture: true});
    window.addEventListener("keydown", first, {once: true, capture: true});
  }
  document.addEventListener("visibilitychange", () => hum.pause(document.hidden || document.body.classList.contains("playing")));
  showSound();
  // "Open full page": a short fade before the page goes.
  $("player-open").addEventListener("click", (e) => {
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    e.preventDefault();
    const href = $("player-open").href, f = $("fade");
    f.hidden = false;
    f.classList.add("leaving");
    requestAnimationFrame(() => { f.style.opacity = "1"; });
    setTimeout(() => { (window.top || window).location.assign(href); }, reducedMotion ? 120 : 260);
  });
  // Back to this page from a game it navigated to (the bfcache): standing again.
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted || !tr) return;
    tr = HallPlay.machine({reduced: reducedMotion});
    playing = null;
    unloadFrame();
    const f = $("fade");
    f.classList.remove("leaving"); f.style.opacity = "0"; f.hidden = true;
    document.body.classList.remove("moving");
    lastNow = 0;
    kit.start();
  });

  /* ----------------------------------------------------------- input */
  const keys = new Set();
  let stickIn = {forward: 0, right: 0, run: false}, stickPointer = null, touchSeen = touchFirst;
  const typing = (e) => e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
  const MOVE = new Set(["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift"]);
  window.addEventListener("keydown", (e) => {
    if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (tr && tr.state !== "idle") {
      if (k === "escape") { if (tr.state === "playing") closeFrame(); else tr.skip(nowMs()); e.preventDefault(); }
      return;
    }
    if (MOVE.has(k)) { keys.add(k); target = null; e.preventDefault(); e.stopPropagation(); }
    else if ((k === "e" || k === "enter") && !e.repeat && near && document.activeElement !== $("prompt")) {
      play(near); e.preventDefault();
    }
  }, true);
  window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()), true);
  window.addEventListener("blur", () => keys.clear());
  $("prompt").addEventListener("click", () => near && play(near));

  function setTouch() {
    if (touchSeen && document.body.classList.contains("touch")) return;
    touchSeen = true;
    document.body.classList.add("touch");
    $("stick").hidden = !!playing;
  }
  window.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch") setTouch(); }, true);

  const stickEl = $("stick"), knob = $("knob"), STICK_R = 54;
  function stickMove(e) {
    const r = stickEl.getBoundingClientRect();
    const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
    stickIn = W.stick(dx, dy, STICK_R);
    const m = Math.hypot(dx, dy), k = m > STICK_R ? STICK_R / m : 1;
    knob.style.transform = `translate(${dx * k}px, ${dy * k}px)`;
    target = null;
  }
  stickEl.addEventListener("pointerdown", (e) => {
    e.preventDefault(); stickPointer = e.pointerId;
    try { stickEl.setPointerCapture(e.pointerId); } catch (err) { /* synthetic */ }
    stickMove(e);
  });
  stickEl.addEventListener("pointermove", (e) => { if (e.pointerId === stickPointer) stickMove(e); });
  const stickEnd = (e) => {
    if (e.pointerId !== stickPointer) return;
    stickPointer = null; stickIn = {forward: 0, right: 0, run: false}; knob.style.transform = "";
  };
  stickEl.addEventListener("pointerup", stickEnd);
  stickEl.addEventListener("pointercancel", stickEnd);

  // Mouse look: the pointer is locked and every movement turns the view.
  const lookBtn = $("look");
  lookBtn.addEventListener("click", () => { try { canvas.requestPointerLock(); } catch (e) { /* unsupported */ } });
  document.addEventListener("pointerlockchange", () => {
    lookBtn.setAttribute("aria-pressed", String(document.pointerLockElement === canvas));
  });
  document.addEventListener("mousemove", (e) => {
    if (document.pointerLockElement !== canvas || !kit) return;
    kit.cam.yaw += e.movementX * 0.0026;
    kit.cam.pitch = Math.min(Math.max(kit.cam.pitch + e.movementY * 0.0026, -1.2), 1.2);
  });
  canvas.addEventListener("click", () => { if (document.pointerLockElement === canvas && near) play(near); });

  const helpBtn = $("help-btn");
  function showHelp(on) { $("help").hidden = !on; helpBtn.setAttribute("aria-expanded", String(on)); }
  helpBtn.addEventListener("click", () => showHelp($("help").hidden));

  /* ---------------------------------------------- the frame, each tick */
  let lastNow = 0, lastSave = 0, lastPrompt = "";
  // How far in front of a cabinet to stop: further on a tall, narrow
  // (portrait phone) view, so the whole cabinet stays in sight.
  function standOff() { return canvas.clientWidth < canvas.clientHeight ? 1.9 : 1.15; }
  function view() {
    return {x: me.x, y: W.EYE, z: me.z, yaw: kit.cam.yaw, pitch: kit.cam.pitch,
      aspect: canvas.clientWidth / Math.max(canvas.clientHeight, 1), fov: W.FOV};
  }
  function tick(t, now, dt) {
    if (!me) return;
    life(t);
    if (tr) {
      const u = stepPlay(now);
      if (u.state !== "idle") {
        // Moving into or out of a game: the camera is the move's, and walking waits.
        if (u.camera) Object.assign(kit.cam, {tx: u.camera.x, ty: u.camera.y, tz: u.camera.z,
          yaw: u.camera.yaw, pitch: u.camera.pitch});
        state.frames++;
        return;
      }
    }
    me.yaw = kit.cam.yaw; me.pitch = kit.cam.pitch;
    const has = (k) => (keys.has(k) ? 1 : 0);
    let input = {
      forward: Math.max(-1, Math.min(1, has("w") + has("arrowup") - has("s") - has("arrowdown") + stickIn.forward)),
      right: Math.max(-1, Math.min(1, has("d") - has("a") + stickIn.right)),
      turn: (has("arrowright") - has("arrowleft")) * 1.9,
      run: keys.has("shift") || stickIn.run,
    };
    if (target && !input.forward && !input.right) {
      const dx = target.x - me.x, dz = target.z - me.z, d = Math.hypot(dx, dz);
      if (d < 0.08) {
        if (target.yaw != null) {
          let dy = target.yaw - me.yaw;
          dy = Math.atan2(Math.sin(dy), Math.cos(dy));
          me.yaw += dy * Math.min(1, dt * 8);
          if (Math.abs(dy) < 0.01) target = null;
        } else target = null;
      } else {
        const want = Math.atan2(-dz, -dx);  // the yaw that looks along (dx, dz)
        let dy = Math.atan2(Math.sin(want - me.yaw), Math.cos(want - me.yaw));
        me.yaw += dy * Math.min(1, dt * 5);
        const fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw), rx = Math.sin(me.yaw), rz = -Math.cos(me.yaw);
        const k = Math.min(1, d / 0.6);
        input = Object.assign(input, {forward: (dx * fx + dz * fz) / d * k, right: (dx * rx + dz * rz) / d * k});
        const before = {x: me.x, z: me.z};
        me = W.step(me, input, dt, world);
        if (dt > 0 && Math.hypot(me.x - before.x, me.z - before.z) < W.WALK * dt * 0.05) target.stuck = (target.stuck || 0) + dt;
        if (target && target.stuck > 0.4) target = null;
        input = null;
      }
    }
    if (input) me = W.step(me, input, dt, world);
    kit.cam.yaw = me.yaw;
    kit.cam.tx = me.x; kit.cam.ty = W.EYE; kit.cam.tz = me.z;
    near = W.near(me, layout);
    if (now - lastSave > 500) { lastSave = now; savePlace(); }
    if (posterQueue.length && posterBusy < 2) pumpPosters();
    state.walking = !!target;
    state.frames++;
  }
  function after() {
    let html = "", cls = "";
    if (near && !(tr && tr.state !== "idle")) {
      if (!near.deployed) { html = `${esc(near.title)}<span class="t">Coming soon</span>`; cls = "soon"; }
      else html = (touchSeen ? "Tap to play " : "<kbd>E</kbd> Play ") + esc(near.title)
        + `<span class="t">${touchSeen ? "" : "Press E or click &middot; "}${esc(near.slug)}.play</span>`;
    }
    if (html !== lastPrompt) {
      lastPrompt = html;
      const p = $("prompt");
      p.hidden = !html;
      p.innerHTML = html;
      p.className = cls;
      p.disabled = cls === "soon";
      $("where").textContent = near ? near.title : `${layout.cabinets.length} games · walk up to one to play`;
    }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  /* ------------------------------------------------------------ boot */
  async function boot() {
    const res = await fetch("layout.json", {cache: "no-cache"});
    if (!res.ok) throw new Error("layout " + res.status);
    layout = await res.json();
    world = W.world(layout);
    document.body.classList.toggle("touch", touchFirst);
    // Reloaded into the other isolation mode with a game open: its poster
    // while the hall loads, so the move into the game reads as one.
    const go = params.get("play");
    const resuming = go && layout.cabinets.find((k) => k.slug === go && k.deployed && canFrame(k) === "frame");
    mod = await StrataLoader.load({script: "hall-engine.js", factory: "createHallEngine", wasm: "hall-engine.wasm",
      title: resuming ? resuming.title : "the arcade hall",
      poster: resuming && resuming.poster || "posters/roam.jpg", fallback: {href: "../", text: "See every game as a list"}});
    me = startPlace();
    kit = StrataKit.create({
      module: mod, canvas,
      camera: {yaw: me.yaw, pitch: me.pitch, dist: 1, tx: me.x, ty: W.EYE, tz: me.z},
      limits: {minPitch: -1.2, maxPitch: 1.2, minDist: 1, maxDist: 1},
      idleOrbit: false,
      dprCap: 1.5,
      frame: tick,
      after,
      onKey: () => true,  // the hall's own keys are on window
      pick(x, y) {
        const v = view();
        return W.pick(v, x / canvas.clientWidth * 2 - 1, 1 - y / canvas.clientHeight * 2, layout);
      },
      idOf: (hit) => (hit.cabinet ? hit.cabinet.slug : "floor"),
      onTap(hit) {
        if (tr && tr.state !== "idle") { if (tr.state !== "playing") tr.skip(nowMs()); return; }
        if (!hit || document.pointerLockElement === canvas) return;
        if (hit.cabinet) {
          if (near === hit.cabinet) { play(hit.cabinet); return; }
          target = W.front(hit.cabinet, standOff());
        } else if (hit.floor) {
          const p = W.resolve(hit.floor.x, hit.floor.z, world);
          target = {x: p.x, z: p.z};
        }
      },
      onSlow: () => StrataLoader.slow(),
      onFatal: (code, msg) => StrataLoader.fallback(code, msg),
    });
    buildScene();
    tr = HallPlay.machine({reduced: reducedMotion});
    if (resuming) {
      // Pick up the move where the other mode left it: at the screen, the game loading behind it.
      playing = resuming;
      dressPlayer(resuming);
      standAt = standPose();
      const to = screenPose(resuming);
      if (!reducedMotion) Object.assign(kit.cam, {tx: to.x, ty: to.y, tz: to.z, yaw: to.yaw, pitch: to.pitch});
      document.body.classList.add("moving");
      tr.resume(nowMs(), {from: standAt, to});
    }
    kit.start();
    StrataLoader.done();
    if (touchSeen) $("stick").hidden = false;
    if (!resuming) {
      showHelp(true);
      setTimeout(() => showHelp(false), 9000);
    }
    canvas.focus({preventScroll: true});
    queuePosters();
    savePlace();
  }

  window.__hall = {
    state,
    get me() { return me ? {x: me.x, z: me.z, yaw: me.yaw, pitch: me.pitch} : null; },
    get near() { return near ? near.slug : null; },
    get playing() { return playing && tr && tr.state === "playing" ? playing.slug : null; },
    get move() { return tr ? tr.state : null; },
    skip() { if (tr) tr.skip(nowMs()); },
    get layout() { return layout; },
    get sound() { return {on: hum.on, running: hum.running}; },
    get kit() { return kit; },
    place(x, z, yaw, pitch) { me = Object.assign({}, me, W.resolve(x, z, world)); if (yaw != null) kit.cam.yaw = me.yaw = yaw; if (pitch != null) kit.cam.pitch = pitch; },
    walkTo(slug) { const c = layout.cabinets.find((k) => k.slug === slug); if (c) target = W.front(c, standOff()); return !!c; },
    play(slug) { play(layout.cabinets.find((k) => k.slug === slug)); },
    back: closeFrame,
    howFor(slug) { const c = layout.cabinets.find((k) => k.slug === slug); return c ? canFrame(c) : null; },
  };
  boot().catch((e) => { console.error("hall:", e); state.error = String(e && e.message || e); });
})();

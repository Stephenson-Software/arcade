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
  function checker(size = 256, cells = 8) {
    const [, ctx] = canvas2d(size, size), s = size / cells;
    for (let i = 0; i < cells; i++) for (let j = 0; j < cells; j++) {
      ctx.fillStyle = (i + j) % 2 ? "rgb(30,28,44)" : "rgb(12,11,20)";
      ctx.fillRect(i * s, j * s, s, s);
    }
    return pixels(ctx, size, size);
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
  function buildScene() {
    const body = new MeshBuilder(), strip = new MeshBuilder();
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
      points.push([...P(0, 2.35, 0.3), 0, 1.0, ...c.colour, 0.12]);
      c.glow = c.colour.map((v) => 0.35 + 0.65 * v);
      texture(screenSlot(i), SCREEN_TEX[0], SCREEN_TEX[1], titleCard(c), TEX_MIPS | TEX_CLAMP);
      texture(marqueeSlot(i), MARQUEE_TEX[0], MARQUEE_TEX[1], marquee(c), TEX_MIPS | TEX_CLAMP);
      for (const [rect, slot] of [[cab.screen, screenSlot(i)], [cab.marquee, marqueeSlot(i)]]) {
        const [x0, y0, x1, y1, z] = rect, q = new MeshBuilder();
        q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1));
        mesh(slot, q, slot, 1 /* STRATA_MESH_UNLIT */);
      }
    });
    mesh(0, body);

    const room = layout.room, w = room.halfWidth, near = room.near, far = room.far, h = room.height;
    const floor = new MeshBuilder(), reps = [2 * w / 1.6, (near - far) / 1.6];
    floor.quad([[-w, 0, near], [w, 0, near], [w, 0, far], [-w, 0, far]], [0, 1, 0], [1, 1, 1],
      [[0, reps[1]], [reps[0], reps[1]], [reps[0], 0], [0, 0]]);
    texture(1, 256, 256, checker(), TEX_MIPS);
    mesh(1, floor, 1);
    const walls = new MeshBuilder();
    walls.quad([[-w, 0, far], [w, 0, far], [w, h, far], [-w, h, far]], [0, 0, 1], [0.10, 0.08, 0.15]);
    for (const x of [-w, w]) {
      let pts = [[x, 0, near], [x, 0, far], [x, h, far], [x, h, near]];
      if (x > 0) pts = [pts[1], pts[0], pts[3], pts[2]];
      walls.quad(pts, [x < 0 ? 1 : -1, 0, 0], [0.08, 0.065, 0.12]);
    }
    walls.quad([[w, 0, near], [-w, 0, near], [-w, h, near], [w, h, near]], [0, 0, -1], [0.08, 0.065, 0.12]);
    // The door you came in by.
    walls.quad([[0.8, 0, near - 0.01], [-0.8, 0, near - 0.01], [-0.8, 2.4, near - 0.01], [0.8, 2.4, near - 0.01]],
      [0, 0, -1], [0.22, 0.15, 0.36]);
    mesh(2, walls);
    // The ceiling's two light strips (lines in the README picture).
    for (const x of [-0.9, 0.9]) {
      strip.quad([[x - 0.03, 3.6, near], [x + 0.03, 3.6, near], [x + 0.03, 3.6, far], [x - 0.03, 3.6, far]],
        [0, -1, 0], [0.75, 0.35, 0.95]);
      strip.quad([[x + 0.03, 3.6, near], [x - 0.03, 3.6, near], [x - 0.03, 3.6, far], [x + 0.03, 3.6, far]],
        [0, 1, 0], [0.75, 0.35, 0.95]);
    }
    mesh(3, strip, -1, 1);
    for (let z = near - 3.0; z > far; z -= 2.4) points.push([0, 3.55, z, 0, 1.2, 0.55, 0.35, 1.0, 0.12]);
    rows(mod._hall_set_items, items);
    rows(mod._hall_set_points, points);
    mod._hall_set_view(0.32, W.FOV);
    setLights();
  }
  function setLights() {
    const end = layout.cabinets.length ? layout.cabinets[0].z : -2;
    const lights = [[0, 3.4, 2.0, 9, 0.7, 0.6, 1.0, 1.2], [0, 3.4, end + 3.0, 9, 0.7, 0.6, 1.0, 1.0]];
    for (const c of layout.cabinets) lights.push([...c.fr.p(0, 1.5, 1.0), 2.6, ...c.glow, 1.4]);
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
          const px = pixels(ctx, w, h);
          texture(screenSlot(i), w, h, px, TEX_MIPS | TEX_CLAMP);
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
    if (c) { const f = W.front(c, standOff()); return {x: f.x, z: f.z, yaw: f.yaw, pitch: 0.12}; }
    const hash = location.hash.startsWith("#p=") ? parsePlace(location.hash.slice(3)) : null;
    return hash || parsePlace(session.get(POS_KEY)) || W.spawn(layout);
  }

  /* --------------------------------------------------------- playing */
  function canFrame(c) {
    if (!layout.embed) return "navigate";
    const iso = !!self.crossOriginIsolated;
    if (c.isolation === iso) return "frame";
    return layout.modes ? "switch" : "navigate";
  }
  function play(c) {
    if (!c || !c.deployed || !c.url) return;
    savePlace();
    const how = canFrame(c);
    state.lastPlay = {slug: c.slug, how};
    if (how === "frame") return openFrame(c);
    if (how === "switch") {
      const url = new URL(location.href);
      url.search = "";
      if (c.isolation) url.searchParams.set("isolated", "1");
      url.searchParams.set("play", c.slug);
      location.assign(url.href);
      return;
    }
    location.assign(c.url);
  }
  function openFrame(c) {
    playing = c;
    $("player-title").textContent = c.title;
    $("player-open").href = c.url;
    $("player-frame").src = c.url;
    $("player").hidden = false;
    document.body.classList.add("playing");
    keys.clear(); stickIn = {forward: 0, right: 0, run: false}; target = null;
    if (document.pointerLockElement) document.exitPointerLock();
    kit.running = false;
    $("back").focus();
  }
  function closeFrame() {
    if (!playing) return;
    const was = playing;
    playing = null;
    $("player").hidden = true;
    $("player-frame").src = "about:blank";
    document.body.classList.remove("playing");
    lastNow = 0;
    kit.start();
    canvas.focus({preventScroll: true});
    state.lastBack = was.slug;
  }
  $("back").addEventListener("click", closeFrame);

  /* ----------------------------------------------------------- input */
  const keys = new Set();
  let stickIn = {forward: 0, right: 0, run: false}, stickPointer = null, touchSeen = touchFirst;
  const typing = (e) => e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
  const MOVE = new Set(["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift"]);
  window.addEventListener("keydown", (e) => {
    if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (playing) { if (k === "escape") closeFrame(); return; }
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
    if (near) {
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
    mod = await StrataLoader.load({script: "hall-engine.js", factory: "createHallEngine", wasm: "hall-engine.wasm",
      title: "the arcade hall", poster: "posters/roam.jpg", fallback: {href: "../", text: "See every game as a list"}});
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
    kit.start();
    StrataLoader.done();
    if (touchSeen) $("stick").hidden = false;
    showHelp(true);
    setTimeout(() => showHelp(false), 9000);
    canvas.focus({preventScroll: true});
    queuePosters();
    const go = params.get("play");
    const c = go && layout.cabinets.find((k) => k.slug === go);
    if (c && c.deployed && canFrame(c) === "frame") openFrame(c);
    savePlace();
  }

  window.__hall = {
    state,
    get me() { return me ? {x: me.x, z: me.z, yaw: me.yaw, pitch: me.pitch} : null; },
    get near() { return near ? near.slug : null; },
    get playing() { return playing ? playing.slug : null; },
    get layout() { return layout; },
    get kit() { return kit; },
    place(x, z, yaw, pitch) { me = Object.assign({}, me, W.resolve(x, z, world)); if (yaw != null) kit.cam.yaw = me.yaw = yaw; if (pitch != null) kit.cam.pitch = pitch; },
    walkTo(slug) { const c = layout.cabinets.find((k) => k.slug === slug); if (c) target = W.front(c, standOff()); return !!c; },
    play(slug) { play(layout.cabinets.find((k) => k.slug === slug)); },
    back: closeFrame,
    howFor(slug) { const c = layout.cabinets.find((k) => k.slug === slug); return c ? canFrame(c) : null; },
  };
  boot().catch((e) => { console.error("hall:", e); state.error = String(e && e.message || e); });
})();

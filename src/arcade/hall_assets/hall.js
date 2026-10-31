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
  // hall3d/main.cpp keeps these meshes drawn after the rest: the room's big
  // surfaces, so the pixels the cabinets hide are never shaded.
  const HALL_MESH_LATE = 0x10000;
  const SCREEN_TEX = [512, 288], MARQUEE_TEX = [512, 112];
  /* The visitor's settings (the panel behind "?"; hall-controls.js keeps
     them in localStorage). Reduce motion starts as the system's preference;
     head bob and the hum start as the older single keys said, else off. */
  const SET = window.HallControls.settings;
  const localStore = (() => { try { return window.localStorage; } catch (e) { return null; } })();
  const settings = SET.load(localStore, {
    reduceMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
    bob: StrataKit.store.get("arcade-hall.bob") === "1",
    hum: StrataKit.store.get("arcade-hall.sound") === "1",
  });
  let reducedMotion = settings.reduceMotion, fov = settings.fov;
  let bobOn = params.has("bob") ? params.get("bob") === "1" : settings.bob;

  const session = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private window, blocked storage */ } },
  };

  let layout = null, world = null, mod = null, kit = null;
  let me = null, near = null, target = null, playing = null;
  const state = {posters: 0, posterErrors: 0, sides: 0, frames: 0, mode: self.crossOriginIsolated ? "isolated" : "plain"};

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
    tri(a, b, c, na, nb, nc, colour) {
      const base = this.positions.length / 3;
      for (const [p, n] of [[a, na], [b, nb], [c, nc]]) {
        this.positions.push(...p); this.normals.push(...n); this.colors.push(...colour); this.uvs.push(0, 0);
      }
      this.indices.push(base, base + 1, base + 2);
    }
    // An upright cylinder in a cabinet's frame: centre (x, y, z), diameter d, height h.
    cylinder(fr, x, y, z, d, h, colour, sides = 10) {
      const r = d / 2, y0 = y - h / 2, y1 = y + h / 2;
      for (let k = 0; k < sides; k++) {
        const a0 = k / sides * 2 * Math.PI, a1 = (k + 1) / sides * 2 * Math.PI;
        const c0 = [Math.cos(a0), Math.sin(a0)], c1 = [Math.cos(a1), Math.sin(a1)];
        const P = (c, yy) => fr.p(x + r * c[0], yy, z + r * c[1]), N = (c) => fr.n(c[0], 0, c[1]);
        this.tri(P(c0, y0), P(c1, y1), P(c1, y0), N(c0), N(c1), N(c1), colour);
        this.tri(P(c0, y0), P(c0, y1), P(c1, y1), N(c0), N(c0), N(c1), colour);
        const up = fr.n(0, 1, 0), down = fr.n(0, -1, 0);
        this.tri(fr.p(x, y1, z), P(c1, y1), P(c0, y1), up, up, up, colour);
        this.tri(fr.p(x, y0, z), P(c0, y0), P(c1, y0), down, down, down, colour);
      }
    }
    // A ball in a cabinet's frame: centre (x, y, z), diameter d.
    sphere(fr, x, y, z, d, colour, rings = 6, sides = 10) {
      const r = d / 2;
      const at = (i, k) => {
        const th = i / rings * Math.PI, ph = k / sides * 2 * Math.PI;
        const n = [Math.sin(th) * Math.cos(ph), Math.cos(th), Math.sin(th) * Math.sin(ph)];
        return [fr.p(x + r * n[0], y + r * n[1], z + r * n[2]), fr.n(...n)];
      };
      for (let i = 0; i < rings; i++) for (let k = 0; k < sides; k++) {
        const a = at(i, k), b = at(i + 1, k), c = at(i + 1, k + 1), e = at(i, k + 1);
        this.tri(a[0], c[0], b[0], a[1], c[1], b[1], colour);
        this.tri(a[0], e[0], c[0], a[1], e[1], c[1], colour);
      }
    }
    // A part of the cabinet's model (hall_model.py) in a cabinet's frame,
    // coloured by role; uv maps its texture coordinates (the side art's atlas).
    model(fr, part, colours, uv, fallback = [1, 1, 1]) {
      const base = this.positions.length / 3, p = part.p, n = part.n, t = part.t;
      for (let k = 0; k < part.r.length; k++) {
        this.positions.push(...fr.p(p[3 * k], p[3 * k + 1], p[3 * k + 2]));
        this.normals.push(...fr.n(n[3 * k], n[3 * k + 1], n[3 * k + 2]));
        this.colors.push(...(colours[part.r[k]] || fallback));
        this.uvs.push(...(t && uv ? uv(t[2 * k], t[2 * k + 1]) : [0, 0]));
      }
      for (const i of part.i) this.indices.push(base + i);
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
    // Clear of the NEW sash in the top-right corner when there is one.
    const [x0, x1] = c.new ? [24, w - 120] : [24, w - 24];
    fitFont(ctx, text, x1 - x0, 62);
    ctx.fillStyle = `rgb(${c.colour.map((v) => Math.round(255 * (0.55 + 0.45 * v)))})`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, (x0 + x1) / 2, h / 2 + 2);
    if (c.new) newRibbon(ctx, w, h);
    return pixels(ctx, w, h);
  }
  /* A "NEW" sash across the marquee's top-right corner, for a game added in
     the last two weeks (hall.py is_new, from /api/games' added). */
  function newRibbon(ctx, w, h) {
    const band = 40, at = 70;  // the sash's width, and how far in from the corner its middle runs
    ctx.save();
    ctx.translate(w - at, at);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = "rgb(255,214,64)";
    ctx.fillRect(-at * 1.6, -band / 2, at * 3.2, band);
    ctx.fillStyle = "rgb(214,40,92)";
    ctx.fillRect(-at * 1.6, -band / 2 + 3, at * 3.2, band - 6);
    ctx.font = `bold 27px "DejaVu Sans", Verdana, system-ui, sans-serif`;
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("NEW", 0, 2);
    ctx.restore();
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
  /* A filtered hall (?tag=halloween, ?org=, ?engine=: layout.json marks each
     cabinet lit or not, hall.py served_layout): the cabinets that do not
     match go dark and recede, with their screen and marquee turned down, their
     glow and light nearly out and their body in shadow. Nothing moves: the
     room, the walkways and every cabinet's place are the same as unfiltered. */
  const DIM_SCREEN = 0.16, DIM_MARQUEE = 0.2, DIM_BODY = 0.42, DIM_LIGHT = 0.12;
  const lit = (c) => c.lit !== false;
  const shade = (c, k) => (lit(c) ? 1 : k);
  // The cabinets' models: each one's detailed mesh and its simple stand-in
  // (hall3d/main.cpp draws one of the two, by the visitor's distance), and
  // one mesh for every cabinet's coin slots (unlit) and side art (one atlas).
  const detailSlot = (i) => 1000 + i, lodSlot = (i) => 2000 + i, ACCENT_SLOT = 900, ART_SLOT = 901;
  function roleColours(roles, org) {
    const out = {};
    for (const [name, spec] of Object.entries(roles)) {
      out[name] = Array.isArray(spec) ? spec : org.map((v) => Math.min(1, spec.org[0] * v + spec.org[1]));
    }
    return out;
  }
  /* The side art's atlas: a cell per cabinet, its organisation's colour until
     its art (posters/<slug>.side.jpg, tools/make_hall_posters.py) arrives. */
  let atlas = null;
  function makeAtlas(cabinets, size) {
    const g = 2, cw = size[0] + 2 * g, ch = size[1] + 2 * g;
    const cols = Math.max(1, Math.min(cabinets.length, Math.floor(2048 / cw))), rows = Math.max(1, Math.ceil(cabinets.length / cols));
    const w = cols * cw, h = rows * ch, [, ctx] = canvas2d(w, h);
    const cell = (i) => [(i % cols) * cw, Math.floor(i / cols) * ch];
    cabinets.forEach((c, i) => {
      const [x, y] = cell(i), grad = ctx.createLinearGradient(0, y, 0, y + ch);
      grad.addColorStop(0, `rgb(${rgb255(c.colour, 150)})`);
      grad.addColorStop(1, `rgb(${rgb255(c.colour, 60)})`);
      ctx.fillStyle = grad; ctx.fillRect(x, y, cw, ch);
    });
    return {w, h, ctx,
      uv: (i) => { const [x, y] = cell(i); return (u, v) => [(x + g + u * size[0]) / w, (y + g + v * size[1]) / h]; },
      draw(i, img) { const [x, y] = cell(i); ctx.drawImage(img, x, y, cw, ch); },
      upload() { texture(ART_SLOT, w, h, pixels(ctx, w, h), TEX_MIPS | TEX_CLAMP); }};
  }
  // How near a cabinet is drawn in detail: closer in economy. The featured
  // cabinet, seen from the door, always is.
  const ECONOMY_LOD = 0.7;
  function setLods() {
    const d = layout.cabinet.model.lodDistance * (economy ? ECONOMY_LOD : 1);
    rows(mod._hall_set_lods, layout.cabinets.map((c, i) => [detailSlot(i), lodSlot(i), c.x, c.z, c.featured ? 1000 : d]));
  }
  let sidesStarted = false;
  function loadSides() {
    sidesStarted = true;
    const jobs = layout.cabinets.map((c, i) => !c.side ? null : new Promise((resolve) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => { try { atlas.draw(i, img); state.sides++; } catch (e) { /* stays its colour */ } resolve(); };
      img.onerror = () => resolve();
      img.src = c.side;
    }));
    // One upload when they are all in: the atlas is large and mipmapped.
    Promise.all(jobs).then(() => { if (state.sides) atlas.upload(); state.sidesDone = true; });
  }
  let scenePoints = null;
  // A cabinet's screen, at a brightness (its vertex colour: the attract-mode shimmer).
  function screenQuad(c, i, b) {
    const [x0, y0, x1, y1, z] = layout.cabinet.screen, fr = c.fr, q = new MeshBuilder();
    const v = b * shade(c, DIM_SCREEN);
    q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1), [v, v, v]);
    mesh(screenSlot(i), q, screenSlot(i), 1 /* STRATA_MESH_UNLIT */);
  }

  /* A cabinet's marquee, lit a little warmer (redder, brighter) the more its
     game is played and liked (hall-fame.js warmth(): only the top few). */
  function marqueeQuad(c, i) {
    const [x0, y0, x1, y1, z] = layout.cabinet.marquee, fr = c.fr, q = new MeshBuilder();
    const m = shade(c, DIM_MARQUEE), w = warmOf(c);
    q.quad([fr.p(x0, y0, z), fr.p(x1, y0, z), fr.p(x1, y1, z), fr.p(x0, y1, z)], fr.n(0, 0, 1),
      [m * (1 + 0.12 * w), m * (1 - 0.03 * w), m * (1 - 0.28 * w)]);
    mesh(marqueeSlot(i), q, marqueeSlot(i), 1 /* STRATA_MESH_UNLIT */);
  }
  const warmOf = (c) => (lit(c) ? c.warm || 0 : 0);
  const WARM_GLOW = [1.0, 0.66, 0.30];
  // The marquee's glow (a soft point above it): toward amber and stronger when warm.
  function glowRow(c) {
    const w = warmOf(c), base = c.colour.map((v) => 0.4 + 0.6 * v);
    return base.map((v, k) => v + (WARM_GLOW[k] - v) * 0.5 * w);
  }
  const glowStrength = (c) => 0.16 * (1 + 0.6 * warmOf(c)) * shade(c, DIM_LIGHT);

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
    if (k >= 0 && (!cs[k].posterPx || cs[k] === near || cs[k] === playing || !lit(cs[k]) || (trailers && trailers.has(k)))) k = -1;
    if (k !== attractIdx) {
      if (attractIdx >= 0 && cs[attractIdx].posterPx) texture(screenSlot(attractIdx), SCREEN_TEX[0], SCREEN_TEX[1], cs[attractIdx].posterPx, TEX_MIPS | TEX_CLAMP);
      if (k >= 0) texture(screenSlot(k), SCREEN_TEX[0], SCREEN_TEX[1], cs[k].titlePx, TEX_MIPS | TEX_CLAMP);
      attractIdx = k;
      state.attract = k >= 0 ? cs[k].slug : null;
    }
    cs.forEach((c, i) => {
      if (me && Math.hypot(c.x - me.x, c.z - me.z) < 8) screenQuad(c, i, HallLife.flicker(t, i));
      scenePoints[c.glowPoint][8] = glowStrength(c) * HallLife.pulse(t, i);
    });
    seasonLife(t);
    pushPoints();
  }
  /* People (hall-people.js): figures other modules hand over, drawn as
     primitives and glow points after the scene's own, every frame there are
     any. They are not obstacles: the visitor walks through them. */
  let sceneItems = [], peopleItems = [], peoplePoints = [];
  function pushPoints() {
    rows(mod._hall_set_points, peoplePoints.length ? scenePoints.concat(peoplePoints) : scenePoints);
  }
  function drawPeople() {
    const P = window.HallPeople;
    if (!P || !scenePoints || !kit) return;
    const out = P.frame({x: kit.cam.tx, y: kit.cam.ty, z: kit.cam.tz, yaw: kit.cam.yaw, pitch: kit.cam.pitch, fov,
      aspect: canvas.clientWidth / Math.max(canvas.clientHeight, 1), width: canvas.clientWidth, height: canvas.clientHeight,
      lite: economy || touchFirst, reduced: reducedMotion, layout});
    state.people = P.stats;
    // Ghosts and fading people: translucent meshes, built once per slot and colour, then only moved.
    for (const b of out.builds) mesh(b.slot, b.mesh, -1, 2 /* STRATA_MESH_TRANSLUCENT */);
    if (out.poses.length) rows(mod._hall_pose_meshes, out.poses);
    if (!out.changed) return;
    peopleItems = out.items; peoplePoints = out.points;
    rows(mod._hall_set_items, peopleItems.length ? sceneItems.concat(peopleItems) : sceneItems);
    pushPoints();
  }
  function buildScene() {
    const accent = new MeshBuilder(), art = new MeshBuilder();
    const cab = layout.cabinet, model = cab.model, items = [], points = [];
    atlas = makeAtlas(layout.cabinets, model.artSize);
    setLods();  // paired before they are made, so a far cabinet's detail is never uploaded
    layout.cabinets.forEach((c, i) => {
      const fr = W.frame(c);
      c.fr = fr;
      const tone = shade(c, DIM_BODY), full = [tone, tone, tone];
      const colours = Object.fromEntries(Object.entries(roleColours(model.roles, c.colour)).map(([k, v]) => [k, v.map((x) => x * tone)]));
      const detail = new MeshBuilder(), lod = new MeshBuilder();
      detail.model(fr, model.detail, colours, undefined, full);
      mesh(detailSlot(i), detail);
      lod.model(fr, model.lod, colours, undefined, full);
      mesh(lodSlot(i), lod);
      accent.model(fr, model.accent, colours, undefined, full);
      art.model(fr, model.art, colours, atlas.uv(i), full);
      const P = (x, y, z) => fr.p(x, y, z);
      c.glowPoint = points.length;
      points.push([...P(0, 2.15, 0.45), 0, 1.3, ...glowRow(c), glowStrength(c)]);
      c.glow = c.colour.map((v) => 0.35 + 0.65 * v);
      c.titlePx = titleCard(c);
      texture(screenSlot(i), SCREEN_TEX[0], SCREEN_TEX[1], c.titlePx, TEX_MIPS | TEX_CLAMP);
      texture(marqueeSlot(i), MARQUEE_TEX[0], MARQUEE_TEX[1], marquee(c), TEX_MIPS | TEX_CLAMP);
      screenQuad(c, i, 1);
      marqueeQuad(c, i);
    });
    scenePoints = points;
    mesh(ACCENT_SLOT, accent, -1, 1 /* STRATA_MESH_UNLIT */);
    atlas.upload();
    mesh(ART_SLOT, art, ART_SLOT);
    buildRoom(points);
    buildSeason(points);
    sceneItems = items;
    rows(mod._hall_set_items, items);
    rows(mod._hall_set_points, points);
    mod._hall_set_view(layout.room.style ? layout.room.style.ambient : 0.32, fov);
    setLights();
  }

  /* The room: walls, carpet, ceiling, the props hall.py lists (the stage,
     the counter, the ceiling panels: plain boxes), its things (stools and
     plush prizes, hall_model.py's parts) and its signs. */
  function buildRoom(points) {
    const room = layout.room, st = room.style, w = room.halfWidth, near = room.near, far = room.far, h = room.height;
    const flat = {p: (x, y, z) => [x, y, z], n: (x, y, z) => [x, y, z]};
    const floor = new MeshBuilder(), reps = [2 * w / CARPET_TILE, (near - far) / CARPET_TILE];
    floor.quad([[-w, 0, near], [w, 0, near], [w, 0, far], [-w, 0, far]], [0, 1, 0], [1, 1, 1],
      [[0, reps[1]], [reps[0], reps[1]], [reps[0], 0], [0, 0]]);
    texture(1, 256, 256, carpet(st), TEX_MIPS);
    mesh(1, floor, 1, HALL_MESH_LATE);
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
    // The ceiling: suspended tiles (a tiling texture), a mesh of its own.
    const ceiling = new MeshBuilder(), ct = room.ceilingTile || 1.2, cr = [2 * w / ct, (near - far) / ct];
    ceiling.quad([[-w, h, far], [w, h, far], [w, h, near], [-w, h, near]], [0, -1, 0], [1, 1, 1],
      [[0, 0], [cr[0], 0], [cr[0], cr[1]], [0, cr[1]]]);
    texture(CEILING_SLOT, 128, 128, ceilingTexture(st), TEX_MIPS);
    mesh(CEILING_SLOT, ceiling, CEILING_SLOT, HALL_MESH_LATE);
    for (const b of room.props) (b.unlit ? lit : walls).box(flat, b.lo, b.hi, b.colour);
    for (const t of room.things || []) {
      const part = room.thingParts[t.part];
      if (part) walls.model(W.frame(t), part, roleColours(layout.cabinet.model.roles, t.colour || [1, 1, 1]));
    }
    mesh(2, walls, -1, HALL_MESH_LATE);
    mesh(3, lit, -1, 1 /* STRATA_MESH_UNLIT */ | HALL_MESH_LATE);
    room.signs.forEach((sg, i) => {
      const slot = signSlot(i), tw = 512, th = Math.round(512 * sg.h / sg.w);
      texture(slot, tw, th, signTexture(sg, tw, th), TEX_MIPS | TEX_CLAMP);
      const q = new MeshBuilder(), x0 = sg.x - sg.w / 2 * sg.facing, x1 = sg.x + sg.w / 2 * sg.facing;
      const y0 = sg.y - sg.h / 2, y1 = sg.y + sg.h / 2;
      q.quad([[x0, y0, sg.z], [x1, y0, sg.z], [x1, y1, sg.z], [x0, y1, sg.z]], [0, 0, sg.facing]);
      mesh(slot, q, slot, 1);
      points.push([sg.x, sg.y, sg.z + 0.15 * sg.facing, 0, sg.w * (sg.neon ? 1.2 : 0.9), ...sg.colour, sg.neon ? 0.16 : 0.10]);
    });
    if (room.fame) buildFame(room.fame, points);
    // A soft pool under each lit ceiling panel's light.
    for (const l of room.lights.slice(2)) points.push([l[0], l[1] + 0.4, l[2], 0, 1.5, ...st.panel, 0.18]);
  }
  const signSlot = (i) => 700 + i, CARPET_TILE = 1.6, CEILING_SLOT = 902;

  /* -------------------------------------- popularity (hall-fame.js)
     The Hall of Fame board by the door lists each leaderboard's best score;
     the marquees of the most played and liked games glow a little warmer.
     Both from public reads of arcade-social (<meta name="arcade-social">);
     without it the board says the scores are resting and the marquees go by
     plays alone. */
  const FAME_SLOT = 905, FAME_TEX = [1024, 636];
  const socialMeta = document.querySelector('meta[name="arcade-social"]');
  const SOCIAL = socialMeta && /^https:\/\/[a-z0-9.-]+$/.test(socialMeta.content) ? socialMeta.content : null;
  let fameView = {state: SOCIAL ? "loading" : "off", rows: [], games: []}, likes = null;
  function drawFame() {
    if (!layout.room.fame || typeof HallFame === "undefined") return;
    const [w, h] = FAME_TEX, [, ctx] = canvas2d(w, h);
    HallFame.draw(ctx, w, h, fameView);
    texture(FAME_SLOT, w, h, pixels(ctx, w, h), TEX_MIPS | TEX_CLAMP);
    state.fame = {state: fameView.state, rows: fameView.rows.length, games: fameView.games.length};
  }
  function buildFame(fm, points) {
    drawFame();
    const q = new MeshBuilder(), x0 = fm.x - fm.w / 2 * fm.facing, x1 = fm.x + fm.w / 2 * fm.facing;
    const y0 = fm.y - fm.h / 2, y1 = fm.y + fm.h / 2;
    q.quad([[x0, y0, fm.z], [x1, y0, fm.z], [x1, y1, fm.z], [x0, y1, fm.z]], [0, 0, fm.facing]);
    mesh(FAME_SLOT, q, FAME_SLOT, 1 /* STRATA_MESH_UNLIT */);
    points.push([fm.x, fm.y, fm.z + 0.2 * fm.facing, 0, fm.w * 1.1, 1.0, 0.78, 0.36, 0.12]);
  }
  async function loadFame() {
    if (!SOCIAL || typeof HallFame === "undefined" || !layout.room.fame) return;
    let store = null;
    try { store = window.sessionStorage; } catch (e) { /* blocked */ }
    const doc = await HallFame.load(SOCIAL, layout.cabinets, store);
    const titles = new Map(layout.cabinets.map((c) => [c.slug, c.title]));
    fameView = {state: doc.off ? "off" : "ready", rows: HallFame.champions(doc.found, layout.cabinets),
      games: doc.games.map((s) => titles.get(s)).filter(Boolean), open: HallFame.open(doc.found, layout.cabinets)};
    drawFame();
  }
  // The marquees' warmth, from plays (live, else the layout's) and likes.
  function applyWarmth() {
    if (typeof HallFame === "undefined" || !scenePoints) return;
    const plays = {};
    for (const c of layout.cabinets) plays[c.slug] = livePlays && livePlays[c.slug] != null ? livePlays[c.slug] : c.plays || 0;
    const w = HallFame.warmth(plays, likes || {}), warm = {};
    layout.cabinets.forEach((c, i) => {
      const v = w[c.slug] || 0;
      if (v) warm[c.slug] = v;
      if (Math.abs((c.warm || 0) - v) < 0.01) return;
      c.warm = v;
      marqueeQuad(c, i);
      const row = scenePoints[c.glowPoint];
      row.splice(5, 4, ...glowRow(c), glowStrength(c));
    });
    rows(mod._hall_set_points, scenePoints);
    state.warm = warm;
  }
  async function refreshLikes() {
    if (!SOCIAL || typeof HallFame === "undefined") return;
    const got = await HallFame.likes(SOCIAL);
    if (got) { likes = got; applyWarmth(); }
  }
  /* The carpet tile: hall.py's carpet_pattern() (make_hall_media.py draws
     the same): squiggles, rings, triangles, stars and confetti, wrapped so
     the tile repeats without seams. */
  function carpet(st) {
    const size = 256, [, ctx] = canvas2d(size, size);
    ctx.fillStyle = `rgb(${rgb255(st.carpet)})`; ctx.fillRect(0, 0, size, size);
    ctx.lineWidth = 2.6; ctx.lineJoin = "round"; ctx.lineCap = "round";
    for (const [kind, x, y, sz, a, k] of st.pattern || []) {
      const col = `rgb(${rgb255(st.carpetDots[k])})`;
      ctx.fillStyle = col; ctx.strokeStyle = col;
      for (const ox of [-size, 0, size]) for (const oy of [-size, 0, size]) {
        ctx.save(); ctx.translate(x + ox, y + oy); ctx.rotate(a);
        ctx.beginPath();
        if (kind === 0) { ctx.arc(0, 0, sz, 0, 2 * Math.PI); ctx.fill(); }
        else if (kind === 1) { ctx.arc(0, 0, sz, 0, 2 * Math.PI); ctx.stroke(); }
        else if (kind === 2) { carpetPath(ctx, carpetTriangle(sz)); ctx.closePath(); ctx.stroke(); }
        else if (kind === 3) { carpetPath(ctx, carpetZigzag(sz)); ctx.stroke(); }
        else { carpetPath(ctx, carpetStar(sz)); ctx.closePath(); ctx.fill(); }
        ctx.restore();
      }
    }
    return pixels(ctx, size, size);
  }
  // The shapes' outlines, round (0, 0) (make_hall_media.py has the same).
  const carpetTriangle = (s) => [0, 1, 2].map((k) => [s * Math.cos(k * 2.0944 - 1.5708), s * Math.sin(k * 2.0944 - 1.5708)]);
  const carpetZigzag = (s) => [0, 1, 2, 3, 4].map((k) => [s * (k / 4 - 0.5), (k % 2 ? 1 : -1) * s * 0.16]);
  const carpetStar = (s) => [...Array(8)].map((_, k) => {
    const r = k % 2 ? s * 0.42 : s, t = k * Math.PI / 4 - Math.PI / 2;
    return [r * Math.cos(t), r * Math.sin(t)];
  });
  function carpetPath(ctx, pts) { pts.forEach(([px, py], k) => (k ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); }
  // Two by two suspended-ceiling tiles, with the T-bars between them.
  function ceilingTexture(st) {
    const size = 128, [, ctx] = canvas2d(size, size);
    ctx.fillStyle = `rgb(${rgb255(st.ceiling)})`; ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = `rgb(${rgb255(st.ceilingGrid || st.ceiling)})`;
    for (const at of [0, size / 2]) { ctx.fillRect(at, 0, 3, size); ctx.fillRect(0, at, size, 3); }
    return pixels(ctx, size, size);
  }
  function signTexture(sg, w, h) {
    if (sg.neon) return neonTexture(sg, w, h);
    const [, ctx] = canvas2d(w, h);
    ctx.fillStyle = "rgb(20,12,18)"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = `rgb(${rgb255(sg.colour)})`; ctx.lineWidth = 5; ctx.strokeRect(6, 6, w - 12, h - 12);
    fitFont(ctx, sg.text, w - 56, Math.round(h * 0.62));
    ctx.fillStyle = `rgb(${sg.colour.map((v) => Math.round(255 * (0.6 + 0.4 * v)))})`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(sg.text, w / 2, h / 2 + 2);
    return pixels(ctx, w, h);
  }
  /* A neon sign: its letters as glowing tubes (a wide soft glow, the tube,
     a pale hot core) and a border tube, on a dark board. */
  function neonTexture(sg, w, h) {
    const [, ctx] = canvas2d(w, h), st = layout.room.style;
    ctx.fillStyle = "rgb(14,8,20)"; ctx.fillRect(0, 0, w, h);
    const tube = (draw, colour, width) => {
      const c = rgb255(colour);
      for (const [blur, lw, col] of [[18, width * 2.2, `rgba(${c},0.55)`], [6, width, `rgb(${c})`],
        [0, width * 0.38, `rgb(${colour.map((v) => Math.round(255 * (0.75 + 0.25 * v)))})`]]) {
        ctx.save(); ctx.shadowBlur = blur; ctx.shadowColor = `rgb(${c})`; ctx.strokeStyle = col; ctx.lineWidth = lw;
        ctx.lineJoin = "round"; ctx.lineCap = "round"; draw(); ctx.restore();
      }
    };
    const m = 14, r = 18;
    tube(() => { ctx.beginPath(); ctx.roundRect ? ctx.roundRect(m, m, w - 2 * m, h - 2 * m, r) : ctx.rect(m, m, w - 2 * m, h - 2 * m); ctx.stroke(); },
      st.neon || [1, 0.36, 0.72], 4);
    fitFont(ctx, sg.text, w - 90, Math.round(h * 0.6));
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    tube(() => ctx.strokeText(sg.text, w / 2, h / 2 + 3), sg.colour, 5);
    return pixels(ctx, w, h);
  }
  /* ------------------------------------------- the season (seasons.py)
     layout.season, when one is in force (or ?season= names one): jack-o'-
     lanterns that flicker, cobwebs in the ceiling corners and a banner.
     A few hundred triangles and soft points, no textures but the banner's,
     so the economy tier keeps its frame rate; walls and walkways are
     unchanged (seasons.py adds the lanterns by the door to the obstacles). */
  const SEASON_BODY = 4, SEASON_FACES = 5, SEASON_WEBS = 6, BANNER_SLOT = 690;
  const FLAME = [1.0, 0.78, 0.28];
  let flames = [];  // each lantern's flame, 0.62..1 (HallLife.candle)
  const lanternFrame = (L) => W.frame({x: L.x, y: L.y, z: L.z, angle: L.angle});
  function lanternFaces(lanterns) {
    const q = new MeshBuilder();
    lanterns.forEach((L, i) => {
      const fr = lanternFrame(L), r = L.size / 2, cy = r * 0.8, b = flames[i] == null ? 0.85 : flames[i];
      const col = FLAME.map((v) => v * b);
      // (u, v) on the front of the pumpkin, in radii, laid onto its surface.
      const at = (u, v) => fr.p(u * r, cy + v * r * 0.8, r * Math.sqrt(Math.max(0, 1 - u * u - v * v)) * 1.03 + 0.003);
      const n = fr.n(0, 0, 1);
      const tri = (a, bb, c) => q.tri(at(...a), at(...bb), at(...c), n, n, n, col);
      tri([-0.5, 0.1], [-0.14, 0.1], [-0.32, 0.44]);
      tri([0.14, 0.1], [0.5, 0.1], [0.32, 0.44]);
      tri([-0.08, -0.06], [0.08, -0.06], [0, 0.1]);
      // A grin: a band that curves up at the ends, with two teeth.
      const steps = 8;
      for (let k = 0; k < steps; k++) {
        const u0 = -0.6 + 1.2 * k / steps, u1 = -0.6 + 1.2 * (k + 1) / steps;
        const top = (u) => -0.30 + 0.22 * (u / 0.6) ** 2, bot = (u) => -0.58 + 0.30 * (u / 0.6) ** 2;
        const tooth = (k === 2 || k === 5) ? 0.12 : 0;
        tri([u0, bot(u0)], [u1, bot(u1)], [u1, top(u1) - tooth]);
        tri([u0, bot(u0)], [u1, top(u1) - tooth], [u0, top(u0) - tooth]);
      }
    });
    return q;
  }
  function cobwebs(webs, h) {
    const q = new MeshBuilder(), col = [0.80, 0.78, 0.84], wid = 0.014;
    const add = (a, b, k) => a.map((v, i) => v + b[i] * k);
    const sub = (a, b) => a.map((v, i) => v - b[i]);
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const unit = (a) => { const m = Math.hypot(...a) || 1; return a.map((v) => v / m); };
    for (const wb of webs) {
      const L = wb.size, x = wb.x + wb.dx * 0.02, z = wb.z + wb.dz * 0.02, y = h - 0.02;
      const A = [x + wb.dx * L, y, z], B = [x, y, z + wb.dz * L], D = [x, y - L * 0.85, z];
      const n = unit(cross(sub(B, A), sub(D, A)));
      const hub = [(A[0] + B[0] + D[0]) / 3 * 0.7 + x * 0.3, (A[1] + B[1] + D[1]) / 3 * 0.7 + y * 0.3,
        (A[2] + B[2] + D[2]) / 3 * 0.7 + z * 0.3];
      const mid = (p, r) => p.map((v, i) => (v + r[i]) / 2);
      const ends = [A, mid(A, B), B, mid(B, D), D, mid(D, A)];
      const strand = (p, r) => {
        const s = unit(cross(sub(r, p), n)).map((v) => v * wid / 2);
        q.quad([sub(p, s), sub(r, s), add(r, s, 1), add(p, s, 1)], n, col);
        q.quad([add(p, s, 1), add(r, s, 1), sub(r, s), sub(p, s)], n.map((v) => -v), col);
      };
      ends.forEach((e) => strand(hub, e));
      for (const f of [0.3, 0.55, 0.8]) {
        const ring = ends.map((e) => add(hub, sub(e, hub), f));
        ring.forEach((p, k) => strand(p, ring[(k + 1) % ring.length]));
      }
    }
    return q;
  }
  function bannerTexture(bn, img) {
    const w = 1024, h = Math.round(1024 * bn.h / bn.w), [, ctx] = canvas2d(w, h);
    ctx.fillStyle = "rgb(28,12,30)"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = `rgb(${rgb255(bn.colour)})`; ctx.lineWidth = 8; ctx.strokeRect(8, 8, w - 16, h - 16);
    const ph = h - 44, pw = Math.round(ph * 16 / 9);
    let tx = 40;
    if (img) {
      const s = Math.max(pw / img.naturalWidth, ph / img.naturalHeight);
      ctx.save(); ctx.beginPath(); ctx.rect(22, 22, pw, ph); ctx.clip();
      ctx.drawImage(img, 22 + (pw - img.naturalWidth * s) / 2, 22 + (ph - img.naturalHeight * s) / 2,
        img.naturalWidth * s, img.naturalHeight * s);
      ctx.restore();
      tx = 22 + pw + 26;
    }
    const cx = (tx + w - 30) / 2, title = bn.title.toUpperCase();
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    fitFont(ctx, title, w - 30 - tx, Math.round(h * 0.36));
    ctx.fillStyle = `rgb(${bn.colour.map((v) => Math.round(255 * (0.6 + 0.4 * v)))})`;
    ctx.fillText(title, cx, h * 0.40);
    fitFont(ctx, bn.line, w - 30 - tx, Math.round(h * 0.15));
    ctx.fillStyle = "rgb(246,226,200)";
    ctx.fillText(bn.line, cx, h * 0.70);
    return [w, h, pixels(ctx, w, h)];
  }
  function buildSeason(points) {
    const ss = layout.season;
    state.season = ss ? ss.name : null;
    document.body.dataset.season = state.season || "";
    if (!ss) return;
    const body = new MeshBuilder();
    flames = ss.lanterns.map(() => 0.85);
    ss.glowAt = points.length;
    ss.lanterns.forEach((L) => {
      const fr = lanternFrame(L), r = L.size / 2, cy = r * 0.8;
      const squash = {p: (x, y, z) => fr.p(x, cy + (y - cy) * 0.8, z), n: fr.n};
      body.sphere(squash, 0, cy, 0, L.size, [0.93, 0.42, 0.05], 7, 12);
      body.cylinder(fr, 0, cy * 2 + 0.02, 0, L.size * 0.12, 0.07, [0.32, 0.36, 0.12], 6);
      points.push([...fr.p(0, cy, r * 1.1), 0, L.size * 2.4, 1.0, 0.58, 0.16, 0.22]);
    });
    if (ss.lanterns.length) mesh(SEASON_FACES, lanternFaces(ss.lanterns), -1, 1 /* STRATA_MESH_UNLIT */);
    if (ss.cobwebs.length) mesh(SEASON_WEBS, cobwebs(ss.cobwebs, layout.room.height), -1, 1);
    const bn = ss.banner;
    if (bn) {
      const flat = {p: (x, y, z) => [x, y, z], n: (x, y, z) => [x, y, z]};
      for (const sx of [-0.4, 0.4]) {
        const x = bn.x + bn.w * sx;
        body.box(flat, [x - 0.01, bn.y + bn.h / 2, bn.z - 0.01], [x + 0.01, bn.ceiling, bn.z + 0.01], [0.2, 0.2, 0.22]);
      }
      const draw = (img) => { const [w, h, px] = bannerTexture(bn, img); texture(BANNER_SLOT, w, h, px, TEX_MIPS | TEX_CLAMP); };
      draw(null);
      const q = new MeshBuilder(), x0 = bn.x - bn.w / 2 * bn.facing, x1 = bn.x + bn.w / 2 * bn.facing;
      const y0 = bn.y - bn.h / 2, y1 = bn.y + bn.h / 2;
      q.quad([[x0, y0, bn.z], [x1, y0, bn.z], [x1, y1, bn.z], [x0, y1, bn.z]], [0, 0, bn.facing]);
      mesh(BANNER_SLOT, q, BANNER_SLOT, 1);
      points.push([bn.x, bn.y, bn.z + 0.15 * bn.facing, 0, bn.w * 0.95, ...bn.colour, 0.12]);
      if (bn.poster) {
        const img = new Image();
        img.decoding = "async";
        img.onload = () => { try { draw(img); state.bannerPoster = true; } catch (e) { /* keep the text banner */ } };
        img.src = bn.poster;
      }
    }
    if (body.indices.length) mesh(SEASON_BODY, body);
  }
  // Each life step: the flames flicker (faces, glow and, outside economy, light).
  function seasonLife(t) {
    const ss = layout.season;
    if (!ss || !ss.lanterns.length) return;
    flames = ss.lanterns.map((L, i) => HallLife.candle(t, i));
    mesh(SEASON_FACES, lanternFaces(ss.lanterns), -1, 1);
    flames.forEach((f, i) => { scenePoints[ss.glowAt + i][8] = 0.24 * f; });
    if (!economy) setLights();
  }
  function seasonLights() {
    const ss = layout.season;
    if (!ss) return [];
    const f = flames.length ? flames.reduce((a, b) => a + b, 0) / flames.length : 0.85;
    return (ss.lights || []).map((l, k) => l.slice(0, 7).concat([l[7] * (k < 2 ? f : 1)]));
  }
  function setLights() {
    if (economy) { rows(mod._hall_set_lights, []); return; }
    const lights = layout.room.lights.slice();
    for (const c of layout.cabinets) lights.push([...c.fr.p(0, 1.5, 1.0), 2.6, ...c.glow, 1.2 * shade(c, DIM_LIGHT)]);
    lights.push(...seasonLights());
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
    // The side art once the screens are in.
    if (!posterQueue.length && !posterBusy && !sidesStarted) loadSides();
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
          if (i !== attractIdx && !(trailers && trailers.shown(i))) texture(screenSlot(i), w, h, px, TEX_MIPS | TEX_CLAMP);
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

  /* ------------------------------------- live screens (hall-trailers.js)
     The nearest screens in sight play their game's trailer instead of the
     poster: two at most, one on a phone or in economy (at 10 fps there), none
     under reduced motion. Each frame goes through the same scanlines as the poster. */
  let trailers = null, trailersAt = -1;
  const TRAILER_PICK_MS = 250, TRAILER_LITE_S = 0.1;
  const trailerMax = () => (reducedMotion ? 0 : economy || touchFirst ? 1 : 2);
  function startTrailers() {
    if (typeof HallTrailers === "undefined" || params.get("trailers") === "0") return;
    trailers = HallTrailers.screens({
      cabinet: (i) => layout.cabinets[i],
      upload(i, w, h, rgba) {
        const t0 = performance.now();
        HallLife.scanlines(rgba, w, h);
        texture(screenSlot(i), w, h, rgba, TEX_MIPS | TEX_CLAMP);
        // What a frame of a trailer costs the page (ms, smoothed), for tools that watch the frame rate.
        state.trailerMs = +(0.9 * (state.trailerMs || 0) + 0.1 * (performance.now() - t0)).toFixed(2);
      },
      restore(i) {
        const c = layout.cabinets[i], px = i === attractIdx ? c.titlePx : c.posterPx || c.titlePx;
        texture(screenSlot(i), SCREEN_TEX[0], SCREEN_TEX[1], px, TEX_MIPS | TEX_CLAMP);
      },
    });
  }
  function stepTrailers(now) {
    if (!trailers) return;
    if (now - trailersAt >= TRAILER_PICK_MS || trailersAt < 0) {
      trailersAt = now;
      trailers.want(HallTrailers.pick(me, layout.cabinets, {max: trailerMax(), playing: trailers.playing}));
      state.trailers = trailers.playing.map((i) => layout.cabinets[i].slug);
    }
    // On a phone or in economy, ten frames a second of the clip's fifteen.
    trailers.draw(now, economy || touchFirst ? TRAILER_LITE_S : HallTrailers.FRAME_S);
    state.trailerHow = trailers.how;
  }
  /* The cabinets' own sounds (hall-life.js): with Sound on, the nearest few
     each play their attract loop, placed by where they stand from the
     visitor (louder near, panned to their side, muffled from behind). */
  const VOICES_MAX = 3, VOICES_LITE = 2, VOICE_MS = 100;
  let voicesAt = -1;
  function stepVoices(now) {
    if (!hum.running || now - voicesAt < VOICE_MS) return;
    voicesAt = now;
    const heard = [];
    for (const c of layout.cabinets) {
      if (!c.deployed || !lit(c)) continue;
      const sp = HallLife.spatial(me, c);
      if (sp.gain > 0.002) heard.push(Object.assign(sp, {id: c.slug, c}));
    }
    heard.sort((a, b) => b.gain - a.gain);
    const list = heard.slice(0, economy || touchFirst ? VOICES_LITE : VOICES_MAX);
    for (const v of list) v.tune = v.c.tune || (v.c.tune = HallLife.tune(v.c));
    hum.cabinets(list);
    state.voices = list.map((v) => ({slug: v.id, gain: +v.gain.toFixed(3), pan: +v.pan.toFixed(2), muffle: v.muffle, wave: v.tune.wave}));
  }
  function pauseTrailers() {
    if (trailers) trailers.pause(document.hidden || !!playing);
  }

  /* ------------------------------------------------- where you stand */
  function savePlace() {
    if (!me) return;
    const v = `${me.x.toFixed(3)},${me.z.toFixed(3)},${me.yaw.toFixed(5)},${me.pitch.toFixed(5)}`;
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
  const SETTLE_MS = 450;  // after the frame's load event, for the game's first paint
  let tr = null, trReduced = reducedMotion, clock = 0, frameToken = 0, standAt = null;
  // The machine's clock: the frame's time when frames are driven by a tool
  // (?drive=1), else the page's (the loop rests while a game is shown).
  const nowMs = () => (kit && kit.driven ? clock : performance.now());
  const standPose = () => ({x: me.x, y: W.EYE, z: me.z, yaw: kit.cam.yaw, pitch: kit.cam.pitch});
  const screenPose = (c) => HallPlay.screenPose(c.fr, layout.cabinet.screen,
    canvas.clientWidth / Math.max(canvas.clientHeight, 1), fov);
  function switchUrl(c) {
    const url = new URL(location.href);
    url.search = "";
    if (c.isolation) url.searchParams.set("isolated", "1");
    if (params.get("season")) url.searchParams.set("season", params.get("season"));
    url.searchParams.set("play", c.slug);
    return url.href;
  }
  function play(c) {
    if (!c || !c.deployed || !c.url || !tr || tr.state !== "idle") return;
    // Reduce motion, if it changed since: the move into the game is a fade, the camera stays.
    if (trReduced !== reducedMotion) { tr = HallPlay.machine({reduced: reducedMotion}); trReduced = reducedMotion; }
    savePlace();
    clearFocus();
    const how = canFrame(c);
    state.lastPlay = {slug: c.slug, how};
    playing = c;
    keys.clear(); stickIn = {forward: 0, right: 0, run: false}; target = null;
    if (me) { me.vx = 0; me.vz = 0; me.speed = 0; }
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
        pauseTrailers();
        state.lastShown = playing.slug;
        startPadLoop();
        if (padSeen) toast("Hold B (or press View) to come back to the hall");
      } else if (e === "unload-frame") unloadFrame();
      else if (e === "navigate") location.assign(playing.url);
      else if (e === "switch") location.assign(switchUrl(playing));
      else if (e === "idle") {
        state.lastBack = playing ? playing.slug : null;
        hum.pause(document.hidden);
        playing = null;
        pauseTrailers();
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
  const hum = HallLife.hum(), soundBtn = $("sound");
  function showSound() {
    soundBtn.setAttribute("aria-pressed", String(hum.on));
    soundBtn.textContent = hum.on ? "Sound on" : "Sound off";
    $("set-hum").checked = hum.on;
    $("set-ghosts").checked = settings.ghosts;
  }
  function setHum(on) {
    hum.set(on);
    settings.hum = hum.on;
    SET.save(localStore, settings);
    showSound();
  }
  soundBtn.addEventListener("click", () => {
    setHum(!hum.on);
    canvas.focus({preventScroll: true});
  });
  // A remembered "on" still waits for a tap: browsers start sound only on one.
  if (settings.hum) {
    const first = () => { if (!hum.on) { hum.set(true); showSound(); } };
    window.addEventListener("pointerdown", first, {once: true, capture: true});
    window.addEventListener("keydown", first, {once: true, capture: true});
  }
  document.addEventListener("visibilitychange", () => {
    hum.pause(document.hidden || document.body.classList.contains("playing"));
    pauseTrailers();
  });
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
    tr = HallPlay.machine({reduced: reducedMotion}); trReduced = reducedMotion;
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
  const typing = (e) => e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== "checkbox";
  const MOVE = new Set(["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright", "shift"]);
  window.addEventListener("keydown", (e) => {
    if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (tr && tr.state !== "idle") {
      if (k === "escape") { if (tr.state === "playing") closeFrame(); else tr.skip(nowMs()); e.preventDefault(); }
      return;
    }
    if (k === "tab" && document.activeElement === canvas && layout && me) {
      if (tabCabinet(e.shiftKey ? -1 : 1)) { e.preventDefault(); e.stopPropagation(); }
      return;
    }
    if (k === "escape" && focused && document.activeElement === canvas) { clearFocus(); target = null; e.preventDefault(); return; }
    if (MOVE.has(k)) {
      keys.add(k); e.preventDefault(); e.stopPropagation();
      if (k !== "shift") { target = null; clearFocus(); }
    } else if ((k === "e" || k === "enter") && !e.repeat) {
      // Enter on a button or link is that control's; on the hall it plays.
      if (k === "enter" && document.activeElement && document.activeElement !== canvas && document.activeElement !== document.body) return;
      // Enter plays the cabinet Tab chose (as announced); E, the one the prompt shows.
      const c = k === "enter" ? (focused || near) : near;
      if (c && document.activeElement !== $("prompt")) { play(c); e.preventDefault(); }
    }
  }, true);

  /* Keyboard and screen-reader access. With the hall focused, Tab and
     Shift+Tab step through the cabinets nearest first, walking to each one
     (the view never turns: an on-screen pointer shows where it is), and the
     live region says which. Past the last (or before the first) Tab leaves
     the hall for the page's other controls, so focus is never trapped
     (Shift+Tab before the walk-through has begun, or after Esc stops it,
     leaves at once). Enter plays the cabinet Tab chose. */
  let focused = null, tabList = null, tabAt = -1, arrivedSaid = null;
  function announce(text) {
    const el = $("announce");
    // Cleared first, so the same words twice are still read twice.
    el.textContent = "";
    setTimeout(() => { el.textContent = text; }, 30);
    state.announced = text;
  }
  function clearFocus() {
    if (!focused && !tabList) return;
    focused = null; tabList = null; tabAt = -1; arrivedSaid = null;
    $("pointer").hidden = true;
  }
  function tabCabinet(dir) {
    if (!tabList) {
      // Shift+Tab before a walk-through has begun leaves the hall backwards, to the page's controls.
      if (dir < 0) return false;
      const at = (c) => { const f = W.front(c, standOff()); return [f.x, f.z]; };
      // In a filtered hall, Tab walks only to the cabinets that are lit.
      tabList = C.order(me, layout.cabinets.filter(lit), at);
      tabAt = -1;
    }
    tabAt += dir;
    if (tabAt < 0 || tabAt >= tabList.length) { clearFocus(); return false; }
    const c = tabList[tabAt];
    focused = c; arrivedSaid = null;
    target = W.front(c, standOff());
    keys.clear();
    const org = c.org || (c.repo ? c.repo.split("/")[0] : "");
    announce(`${c.title}${org ? ", " + org : ""}. ${tabAt + 1} of ${tabList.length}. `
      + (c.deployed ? "Walking there. Press Enter to play." : "Coming soon."));
    state.focused = c.slug;
    return true;
  }
  // The pointer just above the marquee of the cabinet Tab chose, or at the screen's edge towards it.
  function showPointer() {
    const el = $("pointer");
    if (!focused || !me || (tr && tr.state !== "idle")) { el.hidden = true; return; }
    const s = layout.cabinet.screen, v = view(), w = canvas.clientWidth, h = canvas.clientHeight;
    const screenAt = C.project(v, focused.fr.p((s[0] + s[2]) / 2, (s[1] + s[3]) / 2, s[4]));
    // Standing at it with it in sight, no pointer: the card and the prompt say the rest.
    const shown = !(near === focused && screenAt.on);
    el.hidden = !shown;
    // Just above its marquee, or at its screen when the marquee is out of sight up close.
    const above = C.project(v, focused.fr.p((s[0] + s[2]) / 2, layout.cabinet.marquee[3] + 0.22, s[4]));
    const q = above.on || !screenAt.on ? above : screenAt;
    el.classList.toggle("edge", !q.on);
    // Kept clear of the bar along the top.
    el.style.left = `${Math.min(Math.max((q.nx + 1) / 2 * w, 28), w - 28)}px`;
    el.style.top = `${Math.min(Math.max((1 - q.ny) / 2 * h, 84), h - 28)}px`;
    // On screen it points down at the cabinet; off screen, the way to look.
    el.style.transform = `translate(-50%, -50%) rotate(${q.on ? 90 : -q.angle * 180 / Math.PI}deg)`;
    state.pointer = {shown, on: q.on, nx: +q.nx.toFixed(3), ny: +q.ny.toFixed(3)};
    if (near === focused && arrivedSaid !== focused) {
      arrivedSaid = focused;
      announce(focused.deployed ? `At ${focused.title}. Press Enter to play.` : `At ${focused.title}. Coming soon.`);
    }
  }
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

  // Mouse look: the pointer is locked and every movement turns the view
  // (by the look sensitivity and invert setting, applied in tick()).
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

  /* A gamepad (hall-controls.js): the left stick walks, the right stick
     looks, A plays, B goes back. Read once a frame; only the visitor's own
     right stick turns the view. While a game is shown its frame has the pad
     too, so a tap of B is the game's: holding B, or the View/Select button,
     comes back to the hall. */
  const C = window.HallControls, PAD_HOLD_BACK = 0.8;
  let padPrev = null, padBHeld = 0, padSeen = false, toastTimer = 0;
  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    t.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.remove("on"); setTimeout(() => { if (!t.classList.contains("on")) t.hidden = true; }, 300); }, 3200);
  }
  function setPad(gp) {
    padSeen = !!gp;
    document.body.classList.toggle("pad", padSeen);
    state.pad = gp ? C.name(gp) : null;
  }
  window.addEventListener("gamepadconnected", (e) => {
    setPad(e.gamepad);
    toast(`Controller connected: ${C.name(e.gamepad)}`);
  });
  window.addEventListener("gamepaddisconnected", () => {
    const gp = readGamepad();
    setPad(gp);
    if (!gp) { padPrev = null; toast("Controller disconnected"); }
  });
  function readGamepad() {
    try { return navigator.getGamepads ? C.first(navigator.getGamepads()) : null; } catch (e) { return null; }
  }
  // This frame's pad, and which buttons went down since the last one.
  function pollPad() {
    const gp = readGamepad();
    if (!gp) { padPrev = null; return null; }
    if (!padSeen) setPad(gp);
    const p = C.pad(gp), e = C.edges(padPrev, p);
    padPrev = p;
    return Object.assign(p, {down: e});
  }
  // While a game is shown the hall's loop rests, so the pad has a loop of its own.
  let padLoopOn = false, padLoopAt = 0;
  function padLoop(now) {
    if (!playing || !tr || tr.state !== "playing") { padLoopOn = false; return; }
    const dt = padLoopAt ? Math.min((now - padLoopAt) / 1000, 0.25) : 0;
    padLoopAt = now;
    const p = pollPad();
    padBHeld = p && p.b ? padBHeld + dt : 0;
    if (p && (p.down.select || padBHeld >= PAD_HOLD_BACK)) { padBHeld = 0; padLoopOn = false; closeFrame(); return; }
    requestAnimationFrame(padLoop);
  }
  function startPadLoop() {
    if (padLoopOn) return;
    padLoopOn = true; padLoopAt = 0; padBHeld = 0;
    requestAnimationFrame(padLoop);
  }

  const helpBtn = $("help-btn");
  function showHelp(on) { $("help").hidden = !on; helpBtn.setAttribute("aria-expanded", String(on)); }
  helpBtn.addEventListener("click", () => showHelp($("help").hidden));

  /* Settings, in the "?" panel: look sensitivity, invert Y, field of view,
     head bob, reduce motion, the hum and the ghosts. Each applies at once and is kept. */
  const setBtn = $("settings-btn"), setPanel = $("settings");
  function showSettings(on) {
    setPanel.hidden = !on;
    setBtn.setAttribute("aria-expanded", String(on));
  }
  setBtn.addEventListener("click", () => showSettings(setPanel.hidden));
  function applySettings() {
    bobOn = settings.bob;
    reducedMotion = settings.reduceMotion;
    document.body.classList.toggle("reduce", reducedMotion);
    if (fov !== settings.fov) {
      fov = settings.fov;
      if (mod && layout) mod._hall_set_view(economy ? ECONOMY_AMBIENT : (layout.room.style ? layout.room.style.ambient : 0.32), fov);
    }
    state.settings = Object.assign({}, settings);
  }
  function showSettingValues() {
    $("set-sens").value = settings.sensitivity;
    $("set-sens-v").textContent = settings.sensitivity.toFixed(1) + "\u00d7";
    $("set-invert").checked = settings.invertY;
    $("set-fov").value = settings.fov;
    $("set-fov-v").textContent = settings.fov + "\u00b0";
    $("bob").checked = bobOn;
    $("set-reduce").checked = settings.reduceMotion;
    $("set-hum").checked = hum.on;
  }
  function changeSetting(k, v) {
    Object.assign(settings, SET.clean(Object.assign({}, settings, {[k]: v})));
    SET.save(localStore, settings);
    applySettings();
    showSettingValues();
  }
  $("set-sens").addEventListener("input", (e) => changeSetting("sensitivity", +e.target.value));
  $("set-invert").addEventListener("change", (e) => changeSetting("invertY", e.target.checked));
  $("set-fov").addEventListener("input", (e) => changeSetting("fov", +e.target.value));
  $("bob").addEventListener("change", (e) => changeSetting("bob", e.target.checked));
  $("set-reduce").addEventListener("change", (e) => changeSetting("reduceMotion", e.target.checked));
  $("set-hum").addEventListener("change", (e) => setHum(e.target.checked));
  // Ghosts of recent visitors (hall-ghosts.js reads it from __hall.settings).
  $("set-ghosts").addEventListener("change", (e) => changeSetting("ghosts", e.target.checked));
  $("set-reset").addEventListener("click", () => {
    const keepHum = hum.on;
    Object.assign(settings, SET.clean({reduceMotion: matchMedia("(prefers-reduced-motion: reduce)").matches}));
    if (keepHum) setHum(false);
    SET.save(localStore, settings);
    applySettings();
    showSettingValues();
  });
  if (params.has("bob")) settings.bob = bobOn;
  applySettings();
  showSettingValues();

  /* ---------------------------------------------- the frame, each tick */
  let lastNow = 0, lastSave = 0, lastPrompt = "";
  // Head bob, off unless asked for. The view only ever turns when the
  // visitor turns it: nothing here (walking, tap-to-walk) rotates it.
  let bobPhase = 0;
  // The camera as this frame left it: a drag or mouse look moves it between
  // frames, and tick() scales that move by the look sensitivity (and flips
  // its pitch for invert Y). null: adopt the camera as it is (after a move
  // into or out of a game, or a jump).
  let camSeen = null;

  // How far in front of a cabinet to stop: further on a tall, narrow
  // (portrait phone) view, so the whole cabinet stays in sight.
  function standOff() { return canvas.clientWidth < canvas.clientHeight ? 1.9 : 1.15; }
  function view() {
    return {x: me.x, y: W.EYE, z: me.z, yaw: kit.cam.yaw, pitch: kit.cam.pitch,
      aspect: canvas.clientWidth / Math.max(canvas.clientHeight, 1), fov};
  }
  function tick(t, now, dt) {
    if (!me) return;
    try { walk(t, now, dt); } finally { drawPeople(); }
  }
  function walk(t, now, dt) {
    life(t);
    if (tr) {
      const u = stepPlay(now);
      if (u.state !== "idle") {
        // Moving into or out of a game: the camera is the move's, and walking waits.
        if (u.camera) Object.assign(kit.cam, {tx: u.camera.x, ty: u.camera.y, tz: u.camera.z,
          yaw: u.camera.yaw, pitch: u.camera.pitch});
        camSeen = null;
        // B, during the move into a game: finish it now (as Esc does).
        const p = pollPad();
        if (p && p.down.b && u.state !== "playing") tr.skip(now);
        state.frames++;
        return;
      }
    }
    const flip = settings.invertY ? -1 : 1, sens = settings.sensitivity;
    if (camSeen) {
      const dyaw = kit.cam.yaw - camSeen.yaw, dpitch = kit.cam.pitch - camSeen.pitch;
      if (dyaw || dpitch) {
        kit.cam.yaw = camSeen.yaw + dyaw * sens;
        kit.cam.pitch = Math.min(Math.max(camSeen.pitch + dpitch * sens * flip, -1.2), 1.2);
      }
    }
    const pad = pollPad() || {forward: 0, right: 0, run: false, lookX: 0, lookY: 0, down: {}};
    if (pad.lookX || pad.lookY) {
      kit.cam.yaw += pad.lookX * C.LOOK_RATE * sens * dt;
      kit.cam.pitch = Math.min(Math.max(kit.cam.pitch + pad.lookY * C.LOOK_RATE * 0.7 * sens * flip * dt, -1.2), 1.2);
    }
    if (pad.forward || pad.right || pad.lookX || pad.lookY || stickPointer != null) clearFocus();
    if (pad.forward || pad.right) target = null;
    if (pad.down.a && near) { play(near); camSeen = null; state.frames++; return; }
    if (pad.down.b) padBack();
    me.yaw = kit.cam.yaw; me.pitch = kit.cam.pitch;
    const has = (k) => (keys.has(k) ? 1 : 0);
    let input = {
      forward: Math.max(-1, Math.min(1, has("w") + has("arrowup") - has("s") - has("arrowdown") + stickIn.forward + pad.forward)),
      right: Math.max(-1, Math.min(1, has("d") - has("a") + stickIn.right + pad.right)),
      turn: (has("arrowright") - has("arrowleft")) * 1.9 * sens,
      run: keys.has("shift") || stickIn.run || pad.run,
    };
    if (target && !input.forward && !input.right) {
      const dx = target.x - me.x, dz = target.z - me.z, d = Math.hypot(dx, dz);
      if (d < 0.08) {
        target = null;
      } else {
        // Walk there without turning: the step is taken in the view's own frame.
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
    near = W.near(me, layout);
    stepTrailers(now);
    stepVoices(now);
    let eye = W.EYE;
    if (bobOn && !reducedMotion && me.speed > 0.05) {
      bobPhase += dt * 2 * Math.PI * (1.5 + 0.25 * me.speed);
      eye += W.bob(bobPhase, me.speed);
    }
    kit.cam.yaw = me.yaw;
    kit.cam.tx = me.x; kit.cam.ty = eye; kit.cam.tz = me.z;
    camSeen = {yaw: kit.cam.yaw, pitch: kit.cam.pitch};
    if (now - lastSave > 500) { lastSave = now; savePlace(); }
    if (posterQueue.length && posterBusy < 2) pumpPosters();
    state.walking = !!target;
    state.speed = me.speed || 0;
    state.frames++;
  }
  /* The map: a "you are here" plan of the floor, top right. The room, the
     stage and counter, each cabinet in its org colour (the one you are at
     ringed), and you, with the way you look. A click or tap on a cabinet
     walks there (the view does not turn). Open by default on a desktop,
     behind the Map button (or M) on a phone; the choice is remembered. */
  const MAP_KEY = "arcade-hall.map", mapEl = $("map"), mapBtn = $("map-btn");
  let mapOn = false, mapDrawn = "";
  function mapFrame() {
    const r = layout.room, pad = 8, w = mapEl.width, h = mapEl.height;
    const sx = (w - 2 * pad) / (2 * r.halfWidth), sz = (h - 2 * pad) / (r.near - r.far), k = Math.min(sx, sz);
    const ox = w / 2, oz = pad + (h - 2 * pad - (r.near - r.far) * k) / 2;
    // North up is the back wall: z = far at the top, the door at the bottom.
    return {k, toMap: (x, z) => [ox + x * k, oz + (z - r.far) * k], toWorld: (mx, my) => [(mx - ox) / k, r.far + (my - oz) / k]};
  }
  function showMap(on, remember) {
    mapOn = !!on;
    mapEl.hidden = !mapOn;
    mapBtn.setAttribute("aria-expanded", String(mapOn));
    if (remember) StrataKit.store.set(MAP_KEY, mapOn ? "1" : "0");
    mapDrawn = "";
  }
  mapBtn.addEventListener("click", () => { showMap(!mapOn, true); canvas.focus({preventScroll: true}); });
  window.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "m" && !e.repeat && !typing(e) && !e.ctrlKey && !e.metaKey && !e.altKey
      && !(tr && tr.state !== "idle")) showMap(!mapOn, true);
  });
  function drawMap() {
    if (!mapOn || !me || !layout) return;
    const key = `${me.x.toFixed(2)},${me.z.toFixed(2)},${kit.cam.yaw.toFixed(2)},${near ? near.slug : ""}`;
    if (key === mapDrawn) return;
    mapDrawn = key;
    const ctx = mapEl.getContext("2d"), r = layout.room, f = mapFrame(), w = mapEl.width, h = mapEl.height;
    ctx.clearRect(0, 0, w, h);
    const [x0, y0] = f.toMap(-r.halfWidth, r.far), [x1, y1] = f.toMap(r.halfWidth, r.near);
    ctx.fillStyle = "rgba(66, 69, 133, .55)"; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 1; ctx.strokeRect(x0 + .5, y0 + .5, x1 - x0 - 1, y1 - y0 - 1);
    // The door, the stage and the counter.
    const [d0] = f.toMap(r.door[0], r.near), [d1] = f.toMap(r.door[1], r.near);
    ctx.fillStyle = "#f5d79c"; ctx.fillRect(d0, y1 - 3, d1 - d0, 3);
    for (const o of r.obstacles) {
      const [a, b] = f.toMap(o[0], Math.max(o[1], r.far)), [c, d] = f.toMap(o[2], o[3]);
      ctx.fillStyle = "rgba(160, 70, 60, .8)"; ctx.fillRect(a, b, c - a, d - b);
    }
    const fp = layout.cabinet.footprint;
    for (const c of layout.cabinets) {
      const fr = c.fr, pts = [[fp[0], fp[1]], [fp[2], fp[1]], [fp[2], fp[3]], [fp[0], fp[3]]].map(([lx, lz]) => {
        const p = fr.p(lx, 0, lz); return f.toMap(p[0], p[2]);
      });
      ctx.beginPath(); pts.forEach(([a, b], i) => (i ? ctx.lineTo(a, b) : ctx.moveTo(a, b))); ctx.closePath();
      ctx.fillStyle = lit(c) ? `rgb(${rgb255(c.colour)})` : `rgba(${rgb255(c.colour)}, .22)`; ctx.fill();
      if (c === near) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); }
    }
    // You: a dot and the way you look.
    const [mx, my] = f.toMap(me.x, me.z), yaw = kit.cam.yaw, lx = -Math.cos(yaw), lz = -Math.sin(yaw);
    ctx.fillStyle = "rgba(255,255,255,.22)"; ctx.beginPath(); ctx.moveTo(mx, my);
    for (const a of [-0.5, 0.5]) {
      const ca = Math.cos(a), sa = Math.sin(a);
      ctx.lineTo(mx + (lx * ca - lz * sa) * 22, my + (lx * sa + lz * ca) * 22);
    }
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(mx, my, 4, 0, 2 * Math.PI); ctx.fill();
    ctx.strokeStyle = "#120c26"; ctx.lineWidth = 1.5; ctx.stroke();
  }
  // A click or tap on the map: the nearest cabinet to it, or that spot of floor.
  mapEl.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (!layout || (tr && tr.state !== "idle")) return;
    const rect = mapEl.getBoundingClientRect(), f = mapFrame();
    const [x, z] = f.toWorld((e.clientX - rect.left) * mapEl.width / rect.width, (e.clientY - rect.top) * mapEl.height / rect.height);
    let best = null, bestD = 0.9;
    for (const c of layout.cabinets) { const d = Math.hypot(c.x - x, c.z - z); if (d < bestD) { bestD = d; best = c; } }
    keys.clear();
    if (best) target = W.front(best, standOff());
    else { const p = W.settle(x, z, world); target = {x: p.x, z: p.z}; }
    state.mapTarget = best ? best.slug : "floor";
  });

  // B in the hall: close what is open, else stop a walk to somewhere.
  function padBack() {
    if (!setPanel.hidden && !$("help").hidden) { showSettings(false); return; }
    if (!$("help").hidden) { showHelp(false); return; }
    target = null;
  }
  function after() {
    showPointer();
    drawMap();
    let html = "", cls = "";
    if (near && !(tr && tr.state !== "idle")) {
      if (!near.deployed) { html = `${esc(near.title)}<span class="t">Coming soon</span>`; cls = "soon"; }
      else html = (padSeen ? "<kbd>A</kbd> Play " : touchSeen ? "Tap to play " : "<kbd>E</kbd> Play ") + esc(near.title)
        + `<span class="t">${padSeen ? "Press A &middot; " : touchSeen ? "" : "Press E or click &middot; "}${esc(near.slug)}.play</span>`;
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
    showCard(html ? near : null);
  }

  /* The card at a cabinet: its title, organisation, one line about it and
     how often it has been played (live from /api/games, else the layout's). */
  let cardFor = null, livePlays = null;
  function playsText(n) {
    if (!n) return "No plays yet";
    return n === 1 ? "1 play" : `${n.toLocaleString("en-US")} plays`;
  }
  function showCard(c) {
    if (c === cardFor) return;
    cardFor = c;
    document.dispatchEvent(new CustomEvent("hall:card", {detail: c ? c.slug : null}));
    const card = $("card");
    document.body.classList.toggle("at-cabinet", !!c);
    if (!c) { card.classList.remove("on"); return; }
    $("card-org").textContent = c.org || c.repo.split("/")[0];
    $("card-title").textContent = c.title;
    $("card-blurb").textContent = c.blurb || "";
    $("card-blurb").hidden = !c.blurb;
    const plays = livePlays && livePlays[c.slug] != null ? livePlays[c.slug] : c.plays;
    $("card-plays").textContent = playsText(plays);
    card.style.setProperty("--org", `rgb(${rgb255(c.colour)})`);
    card.hidden = false;
    card.classList.add("on");
  }
  async function refreshPlays() {
    try {
      const res = await fetch("/api/games", {cache: "no-cache"});
      if (!res.ok) return;
      const doc = await res.json(), map = {};
      for (const g of doc.games || []) map[g.slug] = g.plays || 0;
      livePlays = map;
      state.livePlays = true;
      applyWarmth();
      if (cardFor) { const c = cardFor; cardFor = null; showCard(c); }
    } catch (e) { /* the layout's counts stand */ }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  /* ------------------------------------------------------------ boot */
  // A software renderer (llvmpipe, SwiftShader: no GPU, or a blocklisted one)
  // draws every pixel on the CPU, where multisampling multiplies the work.
  const SOFTWARE = /llvmpipe|softpipe|lavapipe|swiftshader|software|basic render/i;
  function rendererName() {
    try {
      const gl = document.createElement("canvas").getContext("webgl2");
      if (!gl) return "";
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      const name = String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || "");
      const lose = gl.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
      return name;
    } catch (e) { return ""; }
  }
  function configureEngine() {
    const name = rendererName(), software = SOFTWARE.test(name);
    const aa = params.has("aa") ? params.get("aa") === "1" : !software;
    // Frames are kept for reading back only for tools that drive the hall (?drive=1).
    mod._hall_configure(aa ? 1 : 0, params.get("drive") === "1" ? 1 : 0);
    state.renderer = {name, software, antialias: aa};
    return software;
  }

  /* Economy: below the kit's lowest tier, for a software renderer from the
     start, or for any device still slow there. Half the pixel density, no
     point lights (a brighter ambient instead; the screens, marquees and
     ceiling panels are unlit and keep their glow), and no blur behind the
     page's buttons. On llvmpipe this takes an 800x450 view from about 3 fps
     (q0, antialiased, 6 lights) to about 60. */
  const ECONOMY_SCALE = 0.5, ECONOMY_AMBIENT = 0.9;
  let economy = false;
  function setEconomy(on) {
    economy = !!on;
    state.economy = economy;
    document.body.classList.toggle("lite", economy);
    if (!kit) return;
    if (economy) kit.dprCap = Math.min(kit.dprCap, ECONOMY_SCALE);
    mod._hall_set_view(economy ? ECONOMY_AMBIENT : (layout.room.style ? layout.room.style.ambient : 0.32), fov);
    setLights();
    setLods();
  }


  const FILTER_KEYS = ["tag", "org", "engine"];
  function layoutQuery() {
    const q = new URLSearchParams();
    for (const k of ["season", ...FILTER_KEYS]) if (params.get(k)) q.set(k, params.get(k));
    const s = q.toString();
    return s ? "?" + s : "";
  }
  /* What a filtered hall shows, in the bar: "Halloween: 6 lit", a link back
     to the whole hall (the same spot), and "All games" keeps the filter. */
  function showFilter() {
    const f = layout.filter, el = $("filtered");
    if (!f) { el.hidden = true; return; }
    const all = new URL(location.href);
    for (const k of FILTER_KEYS) all.searchParams.delete(k);
    el.href = all.pathname + all.search + all.hash;
    $("filtered-what").textContent = `${f.summary}: ${f.lit} of ${f.of}`;
    el.setAttribute("aria-label", `Showing ${f.summary} games: ${f.lit} of ${f.of} cabinets lit. Light every cabinet`);
    el.hidden = false;
    document.body.classList.add("filtered");
    $("leave").href = "../?" + f.query;
    state.filter = {summary: f.summary, lit: f.lit, of: f.of};
    // To the whole hall from where the visitor stands now (savePlace keeps it in the hash).
    el.addEventListener("click", () => {
      const now = new URL(location.href);
      for (const k of FILTER_KEYS) now.searchParams.delete(k);
      el.href = now.pathname + now.search + now.hash;
    });
  }

  async function boot() {
    // ?season=halloween (or none) dresses the hall for a season on any date;
    // ?tag=, ?org= and ?engine= light only the cabinets that match.
    const res = await fetch("layout.json" + layoutQuery(), {cache: "no-cache"});
    if (!res.ok) throw new Error("layout " + res.status);
    layout = await res.json();
    showFilter();
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
    const software = configureEngine();
    const wantEconomy = params.has("economy") ? params.get("economy") === "1" : software;
    kit = StrataKit.create({
      module: mod, canvas,
      camera: {yaw: me.yaw, pitch: me.pitch, dist: 1, tx: me.x, ty: W.EYE, tz: me.z},
      limits: {minPitch: -1.2, maxPitch: 1.2, minDist: 1, maxDist: 1},
      idleOrbit: false,
      dprCap: 1.5,
      quality: wantEconomy ? 0 : undefined,
      frame: tick,
      after,
      // The hall's own keys are on window; Tab is left alone, so focus can leave the hall.
      onKey: (e) => e.key !== "Tab",
      pick(x, y, radius) {
        const v = view(), nx = x / canvas.clientWidth * 2 - 1, ny = 1 - y / canvas.clientHeight * 2;
        const hit = W.pick(v, nx, ny, layout);
        // A figure (hall-people.js) in front of what is behind it: its caption, not a walk.
        const P = window.HallPeople;
        const who = P && P.pick ? P.pick(Object.assign(v, {height: canvas.clientHeight}), nx, ny, Math.min(radius || 18, 24)) : null;
        if (who && !(hit && hit.cabinet && hit.t < who.dist - 0.4)) return {person: who};
        return hit;
      },
      idOf: (hit) => (hit.person ? `${hit.person.layer}:${hit.person.id}` : hit.cabinet ? hit.cabinet.slug : "floor"),
      onHover(hit) {
        const who = hit && hit.person && !(tr && tr.state !== "idle") ? hit.person : null;
        canvas.classList.toggle("on-figure", !!who);
        if (window.HallPeople && window.HallPeople.hover) window.HallPeople.hover(who);
      },
      onTap(hit) {
        if (tr && tr.state !== "idle") { if (tr.state !== "playing") tr.skip(nowMs()); return; }
        if (!hit || document.pointerLockElement === canvas) return;
        // A tap on someone shows who (or, for a ghost or a replay, what) they are; nothing else.
        if (hit.person) { window.HallPeople.reveal(hit.person.layer, hit.person.id); state.revealed = `${hit.person.layer}:${hit.person.id}`; return; }
        clearFocus();
        if (hit.cabinet) {
          if (near === hit.cabinet) { play(hit.cabinet); return; }
          target = W.front(hit.cabinet, standOff());
        } else if (hit.floor) {
          const p = W.resolve(hit.floor.x, hit.floor.z, world);
          target = {x: p.x, z: p.z};
        }
      },
      // Still slow at the lowest tier: economy first, then the loader's lighter offer.
      onSlow: () => { if (!economy) setEconomy(true); else StrataLoader.slow(); },
      onFatal: (code, msg) => StrataLoader.fallback(code, msg),
    });
    buildScene();
    if (wantEconomy) setEconomy(true);
    tr = HallPlay.machine({reduced: reducedMotion}); trReduced = reducedMotion;
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
      // Unless the visitor has gone into it (to the settings, say).
      setTimeout(() => { if (setPanel.hidden && !$("help").contains(document.activeElement)) showHelp(false); }, 9000);
    }
    canvas.focus({preventScroll: true});
    queuePosters();
    startTrailers();
    const savedMap = StrataKit.store.get(MAP_KEY);
    showMap(savedMap != null ? savedMap === "1" : !touchSeen, false);
    applyWarmth();
    refreshPlays();
    setInterval(() => { if (!document.hidden) refreshPlays(); }, 60000);
    // arcade-social's reads, once the hall has settled: likes (every few minutes) and the board.
    setTimeout(() => { refreshLikes(); loadFame(); }, 2500);
    setInterval(() => { if (!document.hidden) refreshLikes(); }, 300000);
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
    get map() { return {on: mapOn, target: state.mapTarget || null}; },
    get season() { return layout && layout.season ? layout.season.name : null; },
    get filter() { return layout && layout.filter ? Object.assign({}, layout.filter, {lit: layout.cabinets.filter(lit).map((c) => c.slug)}) : null; },
    economy: (on) => setEconomy(on),
    get sound() { return {on: hum.on, running: hum.running}; },
    get trailers() { return trailers ? trailers.playing.map((i) => ({slug: layout.cabinets[i].slug, shown: trailers.shown(i)})) : []; },
    get card() { const c = $("card"); return c.classList.contains("on") ? {title: $("card-title").textContent, org: $("card-org").textContent, blurb: $("card-blurb").textContent, plays: $("card-plays").textContent} : null; },
    get kit() { return kit; },
    place(x, z, yaw, pitch) {
      me = Object.assign({}, me, W.resolve(x, z, world), {vx: 0, vz: 0, speed: 0});
      if (yaw != null) kit.cam.yaw = me.yaw = yaw;
      if (pitch != null) kit.cam.pitch = pitch;
      camSeen = null;
    },
    get bob() { return bobOn; },
    get focused() { return focused ? focused.slug : null; },
    get settings() { return Object.assign({}, settings, {reducedMotion, fov}); },
    get pad() { return state.pad || null; },
    walkTo(slug) { const c = layout.cabinets.find((k) => k.slug === slug); if (c) target = W.front(c, standOff()); return !!c; },
    play(slug) { play(layout.cabinets.find((k) => k.slug === slug)); },
    back: closeFrame,
    howFor(slug) { const c = layout.cabinets.find((k) => k.slug === slug); return c ? canFrame(c) : null; },
  };
  boot().catch((e) => { console.error("hall:", e); state.error = String(e && e.message || e); });
})();

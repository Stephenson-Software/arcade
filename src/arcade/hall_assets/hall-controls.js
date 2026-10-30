"use strict";
/* The hall's controls, with no DOM and no engine, so the same code runs in
   the page and under node (tests/browser/hall_controls_test.cjs):

     HallControls.pad(gamepad)          -> {forward, right, run, lookX, lookY, a, b, select}
                                           from a "standard" mapping Gamepad
     HallControls.edges(prev, now)      -> {a, b, select}: true on the frame a button went down
     HallControls.LOOK_RATE             -> rad/s at full right-stick deflection
     HallControls.settings.load(storage, fallback) -> the visitor's settings (never throws)
     HallControls.settings.save(storage, s)        -> true if they were kept
     HallControls.settings.clean(s, base)          -> s with every field present, typed and in range
     HallControls.order(me, cabinets, at)  -> the cabinets nearest first (Tab's order); at(c) -> [x, z]
     HallControls.project(view, p)         -> where a point is on screen, or the edge to point from

   The left stick (or the d-pad) walks; the right stick looks, and only the
   visitor's own stick turns the view; A plays; B goes back. A stick inside
   its dead zone reads exactly 0, so a resting, slightly worn stick never
   drifts the walk or turns the view on its own. */
(function (root) {
  const DEAD = 0.18;          // radial dead zone, as a fraction of full deflection
  const RUN_AT = 0.92;        // the left stick pushed this far (or clicked in) runs
  const LOOK_RATE = 2.4;      // rad/s, yaw, at full deflection (pitch is 0.7 of it)

  function axis(gp, i) {
    const v = gp && gp.axes && gp.axes[i];
    return typeof v === "number" && Number.isFinite(v) ? Math.max(-1, Math.min(1, v)) : 0;
  }
  function pressed(gp, i) {
    const b = gp && gp.buttons && gp.buttons[i];
    if (!b) return false;
    return typeof b === "object" ? !!(b.pressed || b.value > 0.5) : b > 0.5;
  }

  /* A stick's (x, y) with a radial dead zone, rescaled so that just outside
     it reads near 0 and full deflection still reads 1. */
  function deadzone(x, y, dead = DEAD) {
    const m = Math.hypot(x, y);
    if (m <= dead) return [0, 0, 0];
    const k = Math.min(1, (m - dead) / (1 - dead)) / m;
    return [x * k, y * k, Math.min(1, m)];
  }

  function pad(gp) {
    const out = {forward: 0, right: 0, run: false, lookX: 0, lookY: 0, a: false, b: false, select: false};
    if (!gp || gp.connected === false) return out;
    const [lx, ly, lm] = deadzone(axis(gp, 0), axis(gp, 1));
    // The d-pad (standard buttons 12-15) walks too.
    const dy = (pressed(gp, 12) ? 1 : 0) - (pressed(gp, 13) ? 1 : 0);
    const dx = (pressed(gp, 15) ? 1 : 0) - (pressed(gp, 14) ? 1 : 0);
    out.forward = Math.max(-1, Math.min(1, -ly + dy));
    out.right = Math.max(-1, Math.min(1, lx + dx));
    out.run = lm > RUN_AT || pressed(gp, 10);
    const [rx, ry] = deadzone(axis(gp, 2), axis(gp, 3));
    // A gentle curve: small deflections aim finely, full deflection turns quickly.
    out.lookX = rx * Math.abs(rx);
    out.lookY = ry * Math.abs(ry);
    out.a = pressed(gp, 0);
    out.b = pressed(gp, 1);
    out.select = pressed(gp, 8);
    return out;
  }

  function edges(prev, now) {
    prev = prev || {};
    return {a: !!now.a && !prev.a, b: !!now.b && !prev.b, select: !!now.select && !prev.select};
  }

  /* The first connected gamepad in a navigator.getGamepads() list (it has
     holes, and entries for pads that went away). */
  function first(list) {
    for (const gp of list || []) if (gp && gp.connected !== false) return gp;
    return null;
  }

  /* A short name for a toast: "Xbox Wireless Controller (STANDARD GAMEPAD
     Vendor: 045e Product: 0b13)" -> "Xbox Wireless Controller". */
  function name(gp) {
    const id = String(gp && gp.id || "").replace(/\s*\(.*$/, "").replace(/^[0-9a-f]{4}-[0-9a-f]{4}-/i, "").trim();
    return id.slice(0, 40) || "Controller";
  }

  /* The settings panel's values, kept as one JSON object in localStorage.
     Storage may be missing or throw (a private window, blocked site data);
     the hall then runs on the defaults and nothing is lost but the memory. */
  const KEY = "arcade-hall.settings";
  const DEFAULTS = Object.freeze({sensitivity: 1, invertY: false, fov: 62, bob: false, reduceMotion: false, hum: false});
  const RANGE = {sensitivity: [0.3, 3], fov: [50, 90]};
  function clean(s, base = DEFAULTS) {
    const out = Object.assign({}, DEFAULTS, base);
    if (!s || typeof s !== "object") return out;
    for (const k of Object.keys(DEFAULTS)) {
      const v = s[k];
      if (typeof DEFAULTS[k] === "boolean") { if (typeof v === "boolean") out[k] = v; continue; }
      const n = typeof v === "string" ? parseFloat(v) : v;
      if (typeof n === "number" && Number.isFinite(n)) out[k] = Math.min(RANGE[k][1], Math.max(RANGE[k][0], n));
    }
    out.sensitivity = Math.round(out.sensitivity * 100) / 100;
    out.fov = Math.round(out.fov);
    return out;
  }
  /* fallback: what stands for a setting never saved (the OS's reduced
     motion, the older single-setting keys for head bob and the hum). */
  function load(storage, fallback) {
    let raw = null;
    try { raw = storage ? storage.getItem(KEY) : null; } catch (e) { raw = null; }
    let saved = null;
    if (raw) { try { saved = JSON.parse(raw); } catch (e) { saved = null; } }
    return clean(saved, clean(fallback));
  }
  function save(storage, s) {
    try { if (!storage) return false; storage.setItem(KEY, JSON.stringify(clean(s))); return true; } catch (e) { return false; }
  }
  const settings = {load, save, clean, KEY, DEFAULTS, RANGE};

  /* Keyboard and screen-reader access: Tab walks to the cabinets in order of
     distance from where the visitor stands (ties by title, so the order is
     stable). at(c) is the spot the distance is measured to. */
  function order(me, cabinets, at) {
    const d = (c) => { const p = at ? at(c) : [c.x, c.z]; return Math.hypot(p[0] - me.x, p[1] - me.z); };
    return cabinets.map((c) => ({c, d: d(c)}))
      .sort((a, b) => a.d - b.d || String(a.c.title).localeCompare(String(b.c.title)))
      .map((e) => e.c);
  }

  /* view: {x, y, z, yaw, pitch, aspect, fov} (HallWalk.ray's); p: [x, y, z].
     -> {on: true, nx, ny} with nx, ny in -1..1 (y up) when p is in sight,
     else {on: false, nx, ny, angle}: a spot near the edge of the screen in
     the direction p lies (angle in radians, 0 = right, counter-clockwise),
     for an arrow that says which way to look. Nothing here moves the view. */
  function project(view, p, margin = 0.9) {
    const cp = Math.cos(view.pitch);
    const f = [-cp * Math.cos(view.yaw), -Math.sin(view.pitch), -cp * Math.sin(view.yaw)];
    let r = [-f[2], 0, f[0]];
    const rl = Math.hypot(r[0], r[2]) || 1;
    r = [r[0] / rl, 0, r[2] / rl];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    const v = [p[0] - view.x, p[1] - view.y, p[2] - view.z];
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const z = dot(v, f), x = dot(v, r), y = dot(v, u);
    const t = Math.tan((view.fov || 62) * Math.PI / 360), aspect = view.aspect || 1;
    if (z > 0.05) {
      const nx = x / (z * t * aspect), ny = y / (z * t);
      if (Math.abs(nx) <= margin && Math.abs(ny) <= margin) return {on: true, nx, ny};
    }
    // Out of sight: which way to turn. Behind, a point straight back reads as "turn right".
    let ax = x, ay = y / aspect;
    if (z <= 0.05 && Math.abs(ax) < 1e-6) ax = 1;
    if (Math.hypot(ax, ay) < 1e-9) ax = 1;
    const angle = Math.atan2(ay, ax), c = Math.cos(angle), s = Math.sin(angle);
    const k = margin / Math.max(Math.abs(c), Math.abs(s));
    return {on: false, nx: c * k, ny: s * k, angle};
  }

  const HallControls = {pad, edges, deadzone, first, name, settings, order, project, DEAD, RUN_AT, LOOK_RATE};
  if (typeof module !== "undefined" && module.exports) module.exports = HallControls;
  else root.HallControls = HallControls;
})(typeof window !== "undefined" ? window : globalThis);

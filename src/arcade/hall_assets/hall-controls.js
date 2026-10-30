"use strict";
/* The hall's controls, with no DOM and no engine, so the same code runs in
   the page and under node (tests/browser/hall_controls_test.cjs):

     HallControls.pad(gamepad)          -> {forward, right, run, lookX, lookY, a, b, select}
                                           from a "standard" mapping Gamepad
     HallControls.edges(prev, now)      -> {a, b, select}: true on the frame a button went down
     HallControls.LOOK_RATE             -> rad/s at full right-stick deflection

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

  const HallControls = {pad, edges, deadzone, first, name, DEAD, RUN_AT, LOOK_RATE};
  if (typeof module !== "undefined" && module.exports) module.exports = HallControls;
  else root.HallControls = HallControls;
})(typeof window !== "undefined" ? window : globalThis);

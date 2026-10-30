"use strict";
/* The walkable hall's maths, with no DOM and no engine, so the same code runs
   in the page and under node (tests/browser/hall_walk_test.cjs):

     HallWalk.frame(cabinet)                 -> its local frame {o, r, f}, p(x, y, z)
     HallWalk.world(layout)                  -> {obstacles, bounds} from /hall/layout.json
     HallWalk.resolve(x, z, world)           -> {x, z} pushed out of cabinets and walls
     HallWalk.step(me, input, dt, world)     -> the visitor after dt seconds of input
     HallWalk.near(me, layout)               -> the cabinet the visitor is at, or null
     HallWalk.front(cabinet, d)              -> {x, z, yaw}: d metres in front of it, facing it
     HallWalk.stick(dx, dy, radius)          -> a joystick offset in CSS px -> {forward, right, run}
     HallWalk.ray(view, nx, ny)              -> a camera ray through normalised screen coords
     HallWalk.pick(view, nx, ny, layout)     -> {cabinet} or {floor: {x, z}} or null

   Coordinates are the layout's (src/arcade/hall.py): metres, door at +z,
   aisle towards -z. The visitor looks along (-cos yaw, -sin yaw) on the
   floor; pitch > 0 looks down (the Strata web kit's orbit convention, which
   the hall reuses as a first-person camera). */
(function (root) {
  const RADIUS = 0.28;              // the visitor, for collisions
  const EYE = 1.62;                 // eye height, metres
  const WALK = 2.4, RUN = 4.6;      // m/s
  const SUBSTEP = 0.04;
  const REACH = 1.75;               // within this of a cabinet's front you can play it
  const FOV = 62;                   // vertical, degrees (hall3d/main.cpp's default)

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function frame(c) {
    const a = c.angle;
    const r = [Math.cos(a), 0, -Math.sin(a)], f = [Math.sin(a), 0, Math.cos(a)];
    const o = [c.x, 0, c.z];
    return {o, r, f,
      p: (x, y, z) => [o[0] + x * r[0] + z * f[0], y, o[2] + x * r[2] + z * f[2]],
      n: (x, y, z) => [x * r[0] + z * f[0], y, x * r[2] + z * f[2]]};
  }

  function world(layout) {
    const fp = layout.cabinet.footprint;
    const obstacles = layout.cabinets.map((c) => ({c, fr: frame(c), x0: fp[0], z0: fp[1], x1: fp[2], z1: fp[3]}));
    const room = layout.room;
    return {obstacles, bounds: [-room.halfWidth, room.far, room.halfWidth, room.near]};
  }

  function resolve(x, z, w, r = RADIUS) {
    for (let iter = 0; iter < 4; iter++) {
      let moved = false;
      for (const o of w.obstacles) {
        const dx = x - o.fr.o[0], dz = z - o.fr.o[2];
        const lx = dx * o.fr.r[0] + dz * o.fr.r[2], lz = dx * o.fr.f[0] + dz * o.fr.f[2];
        if (lx < o.x0 - r || lx > o.x1 + r || lz < o.z0 - r || lz > o.z1 + r) continue;
        const cx = clamp(lx, o.x0, o.x1), cz = clamp(lz, o.z0, o.z1);
        let ex = lx - cx, ez = lz - cz, d = Math.hypot(ex, ez);
        let nx, nz;
        if (d >= r) continue;
        if (d > 1e-6) {
          nx = cx + ex / d * r; nz = cz + ez / d * r;
        } else {
          // Inside: out through the nearest side.
          const pl = lx - o.x0, pr = o.x1 - lx, pb = lz - o.z0, pf = o.z1 - lz;
          const m = Math.min(pl, pr, pb, pf);
          nx = lx; nz = lz;
          if (m === pl) nx = o.x0 - r; else if (m === pr) nx = o.x1 + r;
          else if (m === pb) nz = o.z0 - r; else nz = o.z1 + r;
        }
        x = o.fr.o[0] + nx * o.fr.r[0] + nz * o.fr.f[0];
        z = o.fr.o[2] + nx * o.fr.r[2] + nz * o.fr.f[2];
        moved = true;
      }
      const b = w.bounds;
      const bx = clamp(x, b[0] + r, b[2] - r), bz = clamp(z, b[1] + r, b[3] - r);
      if (bx !== x || bz !== z) { x = bx; z = bz; moved = true; }
      if (!moved) break;
    }
    return {x, z};
  }

  /* input: {forward, right} in -1..1, run, turn (rad/s, keys). me: {x, z, yaw, pitch}. */
  function step(me, input, dt, w) {
    dt = clamp(dt, 0, 0.25);
    let f = input.forward || 0, s = input.right || 0;
    const mag = Math.hypot(f, s);
    if (mag > 1) { f /= mag; s /= mag; }
    let {x, z, yaw} = me;
    yaw += (input.turn || 0) * dt;
    const fx = -Math.cos(yaw), fz = -Math.sin(yaw), rx = Math.sin(yaw), rz = -Math.cos(yaw);
    const speed = input.run ? RUN : WALK;
    const vx = (fx * f + rx * s) * speed, vz = (fz * f + rz * s) * speed;
    if (mag > 0.02) {
      for (let left = dt; left > 1e-6; left -= SUBSTEP) {
        const h = Math.min(SUBSTEP, left);
        const p = resolve(x + vx * h, z + vz * h, w);
        x = p.x; z = p.z;
      }
    }
    return Object.assign({}, me, {x, z, yaw, moving: mag > 0.02});
  }

  function front(c, d = 1.15) {
    const fr = frame(c);
    const p = fr.p(0, 0, 0.72 + d);
    // Facing the cabinet: looking along -f, so yaw with (-cos, -sin) = -f.
    return {x: p[0], z: p[2], yaw: Math.atan2(fr.f[2], fr.f[0])};
  }

  /* The cabinet whose front the visitor stands at (nearest first), preferring
     the one they look towards. */
  function near(me, layout) {
    let best = null, bestScore = Infinity;
    const fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw);
    for (const c of layout.cabinets) {
      const fr = frame(c);
      const p = fr.p(0, 0, 0.72);
      const dx = p[0] - me.x, dz = p[2] - me.z, d = Math.hypot(dx, dz);
      if (d > REACH) continue;
      // In front of it, not behind or beside.
      const side = (me.x - fr.o[0]) * fr.f[0] + (me.z - fr.o[2]) * fr.f[2];
      if (side < 0.5) continue;
      const facing = d > 1e-6 ? (dx * fx + dz * fz) / d : 1;
      const score = d - 0.6 * facing;
      if (score < bestScore) { bestScore = score; best = c; }
    }
    return best;
  }

  function stick(dx, dy, radius) {
    let x = dx / radius, y = -dy / radius;
    const m = Math.hypot(x, y);
    if (m > 1) { x /= m; y /= m; }
    if (m < 0.12) return {forward: 0, right: 0, run: false};
    return {forward: y, right: x, run: m > 0.92};
  }

  /* view: {x, y, z, yaw, pitch, aspect, fov}; nx, ny in -1..1 (y up). */
  function ray(view, nx, ny) {
    const cp = Math.cos(view.pitch);
    const f = [-cp * Math.cos(view.yaw), -Math.sin(view.pitch), -cp * Math.sin(view.yaw)];
    let r = [-f[2], 0, f[0]];
    const rl = Math.hypot(r[0], r[2]) || 1;
    r = [r[0] / rl, 0, r[2] / rl];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    const t = Math.tan((view.fov || FOV) * Math.PI / 360);
    const d = [0, 1, 2].map((i) => f[i] + r[i] * nx * t * view.aspect + u[i] * ny * t);
    const l = Math.hypot(d[0], d[1], d[2]);
    return {o: [view.x, view.y, view.z], d: d.map((v) => v / l)};
  }

  function pick(view, nx, ny, layout) {
    const {o, d} = ray(view, nx, ny);
    let best = null, bestT = Infinity;
    const fp = layout.cabinet.footprint;
    for (const c of layout.cabinets) {
      const fr = frame(c);
      const ox = o[0] - fr.o[0], oz = o[2] - fr.o[2];
      const lo = [ox * fr.r[0] + oz * fr.r[2], o[1], ox * fr.f[0] + oz * fr.f[2]];
      const ld = [d[0] * fr.r[0] + d[2] * fr.r[2], d[1], d[0] * fr.f[0] + d[2] * fr.f[2]];
      const lo3 = [fp[0], 0, fp[1]], hi3 = [fp[2], 2.3, fp[3]];
      let t0 = 0, t1 = Infinity, hit = true;
      for (let i = 0; i < 3; i++) {
        if (Math.abs(ld[i]) < 1e-9) { if (lo[i] < lo3[i] || lo[i] > hi3[i]) { hit = false; break; } continue; }
        let a = (lo3[i] - lo[i]) / ld[i], b = (hi3[i] - lo[i]) / ld[i];
        if (a > b) [a, b] = [b, a];
        t0 = Math.max(t0, a); t1 = Math.min(t1, b);
        if (t0 > t1) { hit = false; break; }
      }
      if (hit && t0 < bestT) { bestT = t0; best = c; }
    }
    if (best && bestT < 40) return {cabinet: best, t: bestT};
    if (d[1] < -1e-3) {
      const t = -o[1] / d[1];
      if (t < 40) return {floor: {x: o[0] + d[0] * t, z: o[2] + d[2] * t}, t};
    }
    return null;
  }

  function spawn(layout) {
    return {x: 0, z: Math.min(5.2, layout.room.near - 1.2), yaw: Math.PI / 2, pitch: 0.06};
  }

  const HallWalk = {frame, world, resolve, step, near, front, stick, ray, pick, spawn,
    RADIUS, EYE, WALK, RUN, REACH, FOV};
  if (typeof module !== "undefined" && module.exports) module.exports = HallWalk;
  else root.HallWalk = HallWalk;
})(typeof window !== "undefined" ? window : globalThis);

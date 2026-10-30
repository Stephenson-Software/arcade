// Unit tests for src/arcade/hall_assets/hall-walk.js, under plain node (no
// dependencies). tests/test_hall.py runs it with a layout from arcade.hall:
//   node tests/browser/hall_walk_test.cjs <layout.json>
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-walk.js"));

const layout = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const world = W.world(layout);
let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.message); }
}
const inside = (p, o) => {
  const dx = p.x - o.fr.o[0], dz = p.z - o.fr.o[2];
  const lx = dx * o.fr.r[0] + dz * o.fr.r[2], lz = dx * o.fr.f[0] + dz * o.fr.f[2];
  return lx > o.x0 && lx < o.x1 && lz > o.z0 && lz < o.z1;
};

test("the visitor starts by the door, clear of every cabinet", () => {
  const s = W.spawn(layout);
  assert.deepStrictEqual(W.resolve(s.x, s.z, world), {x: s.x, z: s.z});
  assert.ok(s.z > 3);
});

test("walking forward from the door goes down the aisle, at walking speed once under way", () => {
  let me = W.spawn(layout);
  for (let i = 0; i < 60; i++) me = W.step(me, {forward: 1}, 1 / 60, world);
  assert.ok(Math.abs(me.x) < 1e-4);
  assert.ok(Math.abs(me.speed - W.WALK) < 0.01, `speed ${me.speed}`);
  const walked = W.spawn(layout).z - me.z;
  // Under way in about a tenth of a second: within 0.3 m of a jolt start.
  assert.ok(walked > W.WALK - 0.3 && walked < W.WALK, `walked ${walked}`);
});

test("walking eases in and out instead of starting and stopping dead", () => {
  let me = W.spawn(layout);
  me = W.step(me, {forward: 1}, 1 / 60, world);
  assert.ok(me.speed > 0 && me.speed < W.WALK * 0.3, `first frame ${me.speed}`);
  for (let i = 0; i < 60; i++) me = W.step(me, {forward: 1}, 1 / 60, world);
  const z0 = me.z;
  let frames = 0;
  while (me.moving && frames < 120) { me = W.step(me, {}, 1 / 60, world); frames++; }
  const coast = z0 - me.z;
  assert.ok(coast > 0.05 && coast < 0.35, `coasted ${coast}`);
  assert.ok(frames < 60, `stopped after ${frames} frames`);
  assert.strictEqual(me.speed, 0);
});

test("the same walk at 30 and 144 fps ends up in the same place", () => {
  const run = (fps) => {
    let me = W.spawn(layout);
    for (let i = 0; i < fps; i++) me = W.step(me, {forward: 1, right: 0.3}, 1 / fps, world);
    return me;
  };
  const a = run(30), b = run(144);
  assert.ok(Math.hypot(a.x - b.x, a.z - b.z) < 0.08, JSON.stringify([a, b]));
});

test("walking into a cabinet at an angle slides along it", () => {
  // The front row nearest the door: its cabinets stand side by side, so a
  // slide either way runs along the row's fronts.
  for (const o of world.obstacles.slice(1, 5)) {
    for (const way of [1, -1]) {
      const fr = o.fr;
      // Just in front of the cabinet, walking into its front at 45 degrees.
      const start = fr.p(-0.2 * way, 0, o.z1 + W.RADIUS + 0.05);
      const dir = [way * fr.r[0] - fr.f[0], way * fr.r[2] - fr.f[2]];
      let me = {x: start[0], z: start[2], yaw: Math.atan2(-dir[1], -dir[0]), pitch: 0};
      for (let i = 0; i < 30; i++) me = W.step(me, {forward: 1}, 1 / 60, world);
      const along = way * ((me.x - start[0]) * fr.r[0] + (me.z - start[2]) * fr.r[2]);
      for (const q of world.obstacles) assert.ok(!inside(me, q), `${o.c.slug}: inside ${q.c ? q.c.slug : "a room obstacle"}`);
      // Half a second at walking speed: well over 0.4 m along the face, not stuck to it.
      assert.ok(along > 0.4, `${o.c.slug} ${way}: slid ${along}`);
    }
  }
});

test("facing a cabinet from its front is its front yaw, and the turn eases there", () => {
  for (const c of layout.cabinets) {
    const f = W.front(c);
    const want = W.faceYaw(f, c);
    assert.ok(Math.abs(Math.atan2(Math.sin(want - f.yaw), Math.cos(want - f.yaw))) < 1e-6, c.slug);
  }
  let yaw = 0;
  const first = W.turnTowards(yaw, 1, 2.6, 1 / 60);
  assert.ok(first > 0 && first < 0.1, `first ${first}`);
  for (let i = 0; i < 120; i++) yaw = W.turnTowards(yaw, 1, 2.6, 1 / 60);
  assert.ok(Math.abs(yaw - 1) < 0.01, `after 2 s ${yaw}`);
  // The short way round.
  assert.ok(W.turnTowards(3, -3, 2.6, 0.1) > 3);
});

test("head bob is nothing when standing and small when walking", () => {
  assert.strictEqual(Math.abs(W.bob(1.3, 0)), 0);
  for (let p = 0; p < 7; p += 0.1) assert.ok(Math.abs(W.bob(p, W.RUN)) < 0.035);
});

test("no cabinet can be walked into, from any direction", () => {
  for (const o of world.obstacles.filter((q) => q.c)) {
    for (let a = 0; a < 16; a++) {
      const ang = a / 16 * 2 * Math.PI;
      // Start 3 m out and walk straight at the cabinet for 4 s.
      let me = {x: o.c.x + 3 * Math.cos(ang), z: o.c.z + 3 * Math.sin(ang), yaw: ang, pitch: 0};
      const p = W.settle(me.x, me.z, world);
      me.x = p.x; me.z = p.z;
      for (let i = 0; i < 40; i++) me = W.step(me, {forward: 1, run: true}, 0.1, world);
      for (const q of world.obstacles) assert.ok(!inside(me, q), `${o.c.slug} from ${a}: inside ${q.c ? q.c.slug : "a room obstacle"}`);
    }
  }
});

test("the walls hold", () => {
  const b = world.bounds;
  for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
    let me = {x: 0, z: 4, yaw, pitch: 0};
    for (let i = 0; i < 100; i++) me = W.step(me, {forward: 1, run: true}, 0.1, world);
    assert.ok(me.x > b[0] && me.x < b[2] && me.z > b[1] && me.z < b[3], JSON.stringify(me));
  }
});

test("a cabinet's front is reachable, faces it and offers it", () => {
  for (const c of layout.cabinets) {
    const f = W.front(c);
    assert.deepStrictEqual(W.resolve(f.x, f.z, world), {x: f.x, z: f.z}, c.slug);
    assert.strictEqual(W.near({x: f.x, z: f.z, yaw: f.yaw}, layout).slug, c.slug);
  }
});

test("behind a cabinet is not in front of it", () => {
  const c = layout.cabinets[1], fr = W.frame(c), p = fr.p(0, 0, -1.2);
  const n = W.near({x: p[0], z: p[2], yaw: 0}, layout);
  assert.ok(!n || n.slug !== c.slug);
});

test("a ray through the centre of the view from a cabinet's front picks it", () => {
  for (const c of layout.cabinets) {
    const f = W.front(c);
    const hit = W.pick({x: f.x, y: W.EYE, z: f.z, yaw: f.yaw, pitch: 0.12, aspect: 16 / 9}, 0, 0, layout);
    assert.ok(hit && hit.cabinet && hit.cabinet.slug === c.slug, c.slug);
  }
});

test("a ray down at the floor picks the floor in front", () => {
  const s = W.spawn(layout);
  const hit = W.pick({x: s.x, y: W.EYE, z: s.z, yaw: s.yaw, pitch: 0.5, aspect: 1}, 0, 0, layout);
  assert.ok(hit.floor && hit.floor.z < s.z && Math.abs(hit.floor.x) < 1e-6);
});

test("the stick has a dead zone and runs at the rim", () => {
  assert.deepStrictEqual(W.stick(2, 2, 54), {forward: 0, right: 0, run: false});
  const up = W.stick(0, -54, 54);
  assert.ok(up.forward === 1 && up.run);
  const right = W.stick(27, 0, 54);
  assert.ok(Math.abs(right.right - 0.5) < 1e-9 && !right.run);
});

test("from the door, the featured cabinet on its stage is in plain sight", () => {
  const s = W.spawn(layout), roam = layout.cabinets.find((c) => c.featured);
  const p = W.frame(roam).p(0, 1.45, 0.3);
  const dx = p[0] - s.x, dz = p[2] - s.z;
  const yaw = Math.atan2(-dz, -dx), pitch = -Math.atan2(p[1] - W.EYE, Math.hypot(dx, dz));
  const hit = W.pick({x: s.x, y: W.EYE, z: s.z, yaw, pitch, aspect: 16 / 9}, 0, 0, layout);
  assert.ok(hit && hit.cabinet && hit.cabinet.slug === roam.slug, JSON.stringify(hit && (hit.cabinet ? hit.cabinet.slug : hit)));
  assert.ok(roam.y > 0.2, "on a raised stage");
});

test("the stage and the counter cannot be walked into", () => {
  const room = world.obstacles.filter((q) => !q.c);
  assert.ok(room.length >= 2);
  for (const o of room) {
    const cx = (o.x0 + o.x1) / 2, cz = (o.z0 + o.z1) / 2;
    assert.ok(!W.clear(cx, cz, world));
    for (let a = 0; a < 16; a++) {
      const ang = a / 16 * 2 * Math.PI;
      const start = W.settle(cx + 6 * Math.cos(ang), cz + 6 * Math.sin(ang), world);
      let me = {x: start.x, z: start.z, yaw: Math.atan2(-(cz - start.z), -(cx - start.x)), pitch: 0};
      for (let i = 0; i < 40; i++) me = W.step(me, {forward: 1, run: true}, 0.1, world);
      for (const q of world.obstacles) assert.ok(!inside(me, q), `walked into an obstacle from ${a}`);
    }
  }
});

test("a place saved inside a cabinet, or outside the room, settles on the nearest walkway", () => {
  for (const o of world.obstacles) {
    const fr = o.fr, lx = (o.x0 + o.x1) / 2, lz = (o.z0 + o.z1) / 2;
    const x = fr.o[0] + lx * fr.r[0] + lz * fr.f[0], z = fr.o[2] + lx * fr.r[2] + lz * fr.f[2];
    const p = W.settle(x, z, world);
    assert.ok(W.clear(p.x, p.z, world), JSON.stringify(p));
    for (const q of world.obstacles) assert.ok(!inside(p, q));
    // Nearby: out through the nearest side (the featured cabinet's is the stage's front).
    assert.ok(Math.hypot(p.x - x, p.z - z) < (o.c ? 2.0 : 3.0), `${o.c ? o.c.slug : "room"}: ${Math.hypot(p.x - x, p.z - z)}`);
  }
  // The old corridor's far end (and its side) is outside the new room.
  for (const [x, z] of [[0, -40], [-20, 2], [2.0, -14.2]]) {
    const p = W.settle(x, z, world);
    assert.ok(W.clear(p.x, p.z, world), JSON.stringify(p));
  }
  // A clear place stays where it is.
  const s = W.spawn(layout);
  assert.deepStrictEqual(W.settle(s.x, s.z, world), {x: s.x, z: s.z});
});

process.exit(failures ? 1 : 0);

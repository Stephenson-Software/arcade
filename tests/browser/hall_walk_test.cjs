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

test("walking forward from the door goes down the aisle", () => {
  let me = W.spawn(layout);
  for (let i = 0; i < 30; i++) me = W.step(me, {forward: 1}, 1 / 30, world);
  assert.ok(Math.abs(me.x) < 1e-9);
  assert.ok(Math.abs(W.spawn(layout).z - me.z - W.WALK) < 0.01, `walked ${W.spawn(layout).z - me.z}`);
});

test("no cabinet can be walked into, from any direction", () => {
  for (const o of world.obstacles) {
    for (let a = 0; a < 16; a++) {
      const ang = a / 16 * 2 * Math.PI;
      // Start 3 m out and walk straight at the cabinet for 4 s.
      let me = {x: o.c.x + 3 * Math.cos(ang), z: o.c.z + 3 * Math.sin(ang), yaw: ang, pitch: 0};
      const p = W.resolve(me.x, me.z, world);
      me.x = p.x; me.z = p.z;
      for (let i = 0; i < 40; i++) me = W.step(me, {forward: 1, run: true}, 0.1, world);
      for (const q of world.obstacles) assert.ok(!inside(me, q), `${o.c.slug} from ${a}: inside ${q.c.slug}`);
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

process.exit(failures ? 1 : 0);

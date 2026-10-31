// Unit tests for src/arcade/hall_assets/hall-ghosts.js, under plain node (no
// dependencies). tests/test_hall.py runs it with a layout from arcade.hall:
//   node tests/browser/hall_ghosts_test.cjs <layout.json>
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const A = path.join(__dirname, "..", "..", "src", "arcade", "hall_assets");
const W = require(path.join(A, "hall-walk.js"));
const G = require(path.join(A, "hall-ghosts.js"));

const layout = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const world = W.world(layout);
const slugs = layout.cabinets.map((c) => c.slug);
let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}
// Inside a cabinet's (or the stage's, or the counter's) footprint, with no allowance.
const insideAny = (x, z) => world.obstacles.some((o) => {
  const dx = x - o.fr.o[0], dz = z - o.fr.o[2];
  const lx = dx * o.fr.r[0] + dz * o.fr.r[2], lz = dx * o.fr.f[0] + dz * o.fr.f[2];
  return lx > o.x0 && lx < o.x1 && lz > o.z0 && lz < o.z1;
});
const levels = (pairs) => Object.fromEntries(pairs);
const busy = levels([[slugs[1], 4], [slugs[2], 3], [slugs[5], 2], [slugs[9], 1], [slugs[20], 1]]);
function run(c, seconds, dt, each) {
  const out = [];
  for (let t = 0; t < seconds; t += dt) { const p = c.step(dt); if (each) each(p, t); out.push(p); }
  return out;
}

test("the generator is deterministic and in 0..1", () => {
  const a = G.rng(42), b = G.rng(42), c = G.rng(43);
  const xs = Array.from({length: 1000}, a), ys = Array.from({length: 1000}, b);
  assert.deepStrictEqual(xs, ys);
  assert.notStrictEqual(c(), G.rng(42)());
  assert.ok(xs.every((v) => v >= 0 && v < 1));
});

test("no activity, no ghosts; levels below 1 or unknown slugs are ignored", () => {
  assert.strictEqual(G.target({}, layout), 0);
  assert.strictEqual(G.target({nope: 4, [slugs[1]]: 0, [slugs[2]]: "4", [slugs[3]]: 2.5}, layout), 0);
  const c = G.crowd(layout, {}, {seed: 1});
  run(c, 60, 0.1);
  assert.strictEqual(c.count, 0);
});

test("busier games get more ghosts, and the cap holds (12 desktop, 6 phone or economy)", () => {
  assert.strictEqual(G.budget({}), 12);
  assert.strictEqual(G.budget({economy: true}), 6);
  assert.strictEqual(G.budget({phone: true}), 6);
  assert.strictEqual(G.target(levels([[slugs[1], 1]]), layout), 1);
  assert.strictEqual(G.target(levels([[slugs[1], 2]]), layout), 1);  // one place at a quiet cabinet
  assert.strictEqual(G.target(levels([[slugs[1], 3]]), layout), 2);  // a busy one has a watcher too
  assert.strictEqual(G.target(busy, layout), 2 + 2 + 1 + 1 + 1);
  const all = Object.fromEntries(slugs.map((s) => [s, 4]));
  assert.strictEqual(G.target(all, layout), 12);
  assert.strictEqual(G.target(all, layout, G.budget({phone: true})), 6);
  const c = G.crowd(layout, all, {seed: 3, cap: 6});
  let most = 0;
  run(c, 300, 0.1, (p) => { most = Math.max(most, p.length); });
  assert.ok(most <= 6, "most " + most);  // leaving ghosts count too
  const d = G.crowd(layout, all, {seed: 3});
  most = 0;
  run(d, 300, 0.1, (p) => { most = Math.max(most, p.length); });
  assert.ok(most <= 12 && most >= 8, "most " + most);
  // Dark cabinets in a filtered hall get none.
  const dark = Object.assign({}, layout, {cabinets: layout.cabinets.map((k) => Object.assign({}, k, {lit: false}))});
  assert.strictEqual(G.target(all, dark), 0);
});

test("the same seed gives the same crowd, frame for frame", () => {
  const a = run(G.crowd(layout, busy, {seed: 7}), 120, 0.1);
  const b = run(G.crowd(layout, busy, {seed: 7}), 120, 0.1);
  assert.deepStrictEqual(a, b);
  const c = run(G.crowd(layout, busy, {seed: 8}), 120, 0.1);
  assert.notDeepStrictEqual(a, c);
});

test("routes go round the cabinets, from the door to any cabinet", () => {
  const g = G.grid(layout, world);
  const from = {x: 0, z: layout.room.near - 0.4};
  for (const k of layout.cabinets) {
    const to = G.place(k, 0, world);
    const path = G.route(g, from, to);
    assert.deepStrictEqual(path[0], from);
    assert.deepStrictEqual(path[path.length - 1], {x: to.x, z: to.z});
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1], b = path[i], n = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 0.05);
      for (let s = 0; s <= n; s++) {
        const x = a.x + (b.x - a.x) * s / n, z = a.z + (b.z - a.z) * s / n;
        assert.ok(!insideAny(x, z), `route to ${k.slug} crosses an obstacle at ${x.toFixed(2)},${z.toFixed(2)}`);
      }
    }
  }
});

test("a ghost's standing place is clear and faces the cabinet's screen", () => {
  for (const k of layout.cabinets.slice(0, 12)) {
    for (const slot of [0, 1]) {
      const p = G.place(k, slot, world);
      assert.ok(W.clear(p.x, p.z, world), `${k.slug} slot ${slot}`);
      const fr = W.frame(k), s = fr.p(0, 1.4, 0.3);
      const lx = -Math.cos(p.yaw), lz = -Math.sin(p.yaw), d = Math.hypot(s[0] - p.x, s[2] - p.z);
      assert.ok((lx * (s[0] - p.x) + lz * (s[2] - p.z)) / d > 0.99, "facing " + k.slug);
    }
  }
});

test("ghosts come in through the door, stand at busy cabinets, never walk through one, and leave", () => {
  const c = G.crowd(layout, busy, {seed: 11});
  const want = c.wanted;
  // About half are already at their cabinets when the hall opens.
  const first = c.step(0.1);
  assert.ok(first.length >= Math.ceil(want / 2) && first.length < want, `${first.length} of ${want}`);
  const seen = new Map(), cabinets = new Set(), busySlugs = new Set(Object.keys(busy));
  let entered = 0, left = 0, played = 0;
  run(c, 600, 0.1, (people) => {
    const ids = new Set();
    for (const p of people) {
      ids.add(p.id);
      assert.ok(!insideAny(p.x, p.z), `${p.id} inside an obstacle at ${p.x},${p.z}`);
      assert.ok(p.alpha >= 0 && p.alpha <= G.ALPHA + 1e-9);
      assert.deepStrictEqual(Object.keys(p).sort(), p.cabinet ? ["alpha", "cabinet", "color", "id", "x", "yaw", "z"] : ["alpha", "color", "id", "x", "yaw", "z"]);
      if (p.cabinet) { assert.ok(busySlugs.has(p.cabinet)); cabinets.add(p.cabinet); played++; }
      if (!seen.has(p.id)) {
        seen.set(p.id, p);
        if (p.z > layout.room.near - 1) entered++;  // first seen at the door
      }
    }
    for (const id of seen.keys()) if (!ids.has(id) && !seen.get(id).gone) {
      seen.get(id).gone = true; left++;
    }
  });
  assert.ok(entered >= 5, "entered " + entered);
  assert.ok(left >= 3, "left " + left);
  assert.ok(played > 0 && cabinets.size >= 3, [...cabinets].join());
  // The crowd stays near its size.
  assert.ok(c.count <= want + 2);
});

test("busier cabinets are visited more", () => {
  const two = levels([[slugs[3], 4], [slugs[4], 1]]);
  const count = {[slugs[3]]: 0, [slugs[4]]: 0};
  for (let seed = 1; seed <= 6; seed++) {
    run(G.crowd(layout, two, {seed}), 400, 0.25, (people) => { for (const p of people) if (p.cabinet) count[p.cabinet]++; });
  }
  assert.ok(count[slugs[3]] > count[slugs[4]], JSON.stringify(count));
});

test("under reduce motion ghosts stand at their cabinets and do not walk", () => {
  const c = G.crowd(layout, busy, {seed: 5, reduced: true});
  const first = c.step(0.1);
  assert.strictEqual(first.length, c.wanted);
  const at = new Map(first.map((p) => [p.id, [p.x, p.z]]));
  run(c, 300, 0.1, (people) => {
    for (const p of people) {
      const was = at.get(p.id);
      if (was) assert.ok(Math.hypot(p.x - was[0], p.z - was[1]) < 1e-9, "moved " + p.id);
      else at.set(p.id, [p.x, p.z]);
    }
  });
  // Turning it on mid-walk puts walkers at their places at once.
  const d = G.crowd(layout, busy, {seed: 5});
  run(d, 20, 0.1);
  d.setReduced(true);
  const a = d.step(0.1), b = d.step(0.1);
  assert.deepStrictEqual(a.map((p) => [p.x, p.z]), b.map((p) => [p.x, p.z]));
});

test("when activity falls away, the ghosts leave", () => {
  const c = G.crowd(layout, busy, {seed: 9});
  run(c, 30, 0.1);
  assert.ok(c.count > 0);
  c.setLevels({});
  run(c, 120, 0.1);
  assert.strictEqual(c.count, 0);
});

if (failures) { console.log(failures + " failed"); process.exit(1); }
console.log("all passed");

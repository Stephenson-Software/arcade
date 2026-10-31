// Unit tests for src/arcade/hall_assets/hall-replays.js, under plain node (no
// dependencies). tests/test_walks.py runs it with two layouts from arcade.hall,
// the second with the cabinets reordered (another layout key):
//   node tests/browser/hall_replays_test.cjs <layout.json> <moved-layout.json>
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const assets = path.join(__dirname, "..", "..", "src", "arcade", "hall_assets");
const W = require(path.join(assets, "hall-walk.js"));
const R = require(path.join(assets, "hall-replays.js"));

const layout = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const moved = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const world = W.world(layout), movedWorld = W.world(moved);
let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}
const onGrid = (v) => Math.abs(v / R.GRID - Math.round(v / R.GRID)) < 1e-9;

/* A visitor walking from the door to a cabinet, sampled every DT like the page does. */
function walkTo(slug, seconds = 30) {
  const c = layout.cabinets.find((k) => k.slug === slug);
  const goal = W.front(c);
  let me = W.spawn(layout);
  const rec = R.recorder();
  for (let t = 0; t < seconds; t += R.DT) {
    for (let i = 0; i < 30; i++) {
      const dx = goal.x - me.x, dz = goal.z - me.z, d = Math.hypot(dx, dz);
      if (d < 0.2) break;
      // Steer straight at it, in the visitor's own frame.
      const fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw), rx = Math.sin(me.yaw), rz = -Math.cos(me.yaw);
      me = W.step(me, {forward: (dx * fx + dz * fz) / d, right: (dx * rx + dz * rz) / d}, R.DT / 30, world);
    }
    rec.sample(me);
    const n = W.near(Object.assign({}, me, {yaw: goal.yaw}), layout);
    rec.visit(n && n.slug);
  }
  return rec;
}

test("the recorder keeps a coarse path: on the grid, no standing still, capped", () => {
  const rec = R.recorder();
  rec.sample({x: 0.02, z: 5.02});
  rec.sample({x: 0.05, z: 4.96});  // the same cell: standing
  assert.strictEqual(rec.points.length, 1);
  for (let i = 1; i < 400; i++) rec.sample({x: 0, z: 5 - i * 1.1});
  assert.strictEqual(rec.points.length, R.MAX_POINTS);
  assert.ok(rec.full);
  for (const [x, z] of rec.points) assert.ok(onGrid(x) && onGrid(z), `${x},${z}`);
});

test("a late timer's gap is filled in; a jump (a link, a reload) ends the walk", () => {
  const rec = R.recorder();
  rec.sample({x: 0, z: 5});
  rec.sample({x: 0, z: 0});  // 5 m in one sample: filled in to steps of at most STEP
  assert.ok(rec.points.length >= 3);
  for (let i = 1; i < rec.points.length; i++) {
    const [a, b] = [rec.points[i - 1], rec.points[i]];
    assert.ok(Math.hypot(b[0] - a[0], b[1] - a[1]) <= R.STEP + 0.36);
  }
  rec.sample({x: 0, z: -20});
  assert.ok(rec.full);
  const n = rec.points.length;
  rec.sample({x: 0, z: -19.5});
  assert.strictEqual(rec.points.length, n);
});

test("visits are recorded once each, in order, at the point reached", () => {
  const rec = R.recorder();
  rec.visit("roam");  // no points yet: ignored
  rec.sample({x: 0, z: 5}); rec.visit("a"); rec.visit("a");
  rec.sample({x: 0, z: 4}); rec.visit("b"); rec.sample({x: 0, z: 3}); rec.visit("a");
  assert.deepStrictEqual(rec.visits, [{slug: "a", at: 0}, {slug: "b", at: 1}, {slug: "a", at: 2}]);
  for (let i = 0; i < 20; i++) { rec.sample({x: 0, z: 2 - i}); rec.visit("s" + i); }
  assert.strictEqual(rec.visits.length, R.MAX_VISITS);
});

test("the payload is the shape arcade accepts, and nothing for a walk too short", () => {
  const short = R.recorder();
  short.sample({x: 0, z: 5});
  assert.strictEqual(short.payload("0123456789abcdef"), null);
  const slug = layout.cabinets[3].slug;
  const rec = walkTo(slug);
  const body = rec.payload(layout.layoutKey);
  assert.deepStrictEqual(Object.keys(body).sort(), ["dt", "layout", "points", "visits"]);
  assert.strictEqual(body.dt, 0.5);
  assert.ok(body.points.length >= R.MIN_POINTS, String(body.points.length));
  assert.strictEqual(body.visits[body.visits.length - 1].slug, slug);
  fs.writeFileSync(process.env.REPLAY_OUT || "/dev/null", JSON.stringify(body));
});

test("same layout key: played as recorded, standing at the cabinet facing it", () => {
  const slug = layout.cabinets[3].slug;
  const walk = walkTo(slug).payload(layout.layoutKey);
  const p = R.plan(walk, layout, world, W);
  assert.strictEqual(p.pts.length, walk.points.length);
  const c = layout.cabinets[3];
  const stop = [...p.stops.entries()].pop();
  assert.strictEqual(stop[1].slug, slug);
  const t = (p.arrive[stop[0]] + p.depart[stop[0]]) / 2;
  const q = R.pose(p, t);
  assert.strictEqual(q.cabinet, slug);
  assert.ok(Math.abs(q.yaw - W.front(c).yaw) < 1e-9);
  assert.ok(W.clear(q.x, q.z, world, W.RADIUS - 0.01));
  // Faster than the walk was, and it fades in and out.
  assert.ok(p.end - p.stops.size * R.PAUSE - 1.2 < (walk.points.length - 1) * R.DT);
  assert.ok(R.pose(p, 0).alpha < 0.05);
  assert.strictEqual(R.pose(p, p.end + 0.5), null);  // between loops
});

test("another layout key: re-anchored to the cabinets by slug, never through one", () => {
  const slug = layout.cabinets[3].slug;
  const walk = walkTo(slug).payload(layout.layoutKey);
  assert.notStrictEqual(layout.layoutKey, moved.layoutKey);
  const p = R.plan(walk, moved, movedWorld, W);
  const c = moved.cabinets.find((k) => k.slug === slug);
  const f = W.front(c), end = p.pts[p.pts.length - 1];
  assert.ok(Math.hypot(end[0] - f.x, end[1] - f.z) < 1e-9, "ends in front of the cabinet where it stands now");
  for (let t = 0; t < p.end; t += 0.05) {
    const q = R.pose(p, t);
    if (q) assert.ok(W.clear(q.x, q.z, movedWorld, 0.05), `inside something at t=${t}: ${q.x},${q.z}`);
  }
  // A walk whose cabinets are all gone, in another layout: dropped.
  const gone = Object.assign({}, walk, {visits: [{slug: "not-here", at: 1}]});
  assert.strictEqual(R.plan(gone, moved, movedWorld, W), null);
});

test("people: the HallPeople contract, staggered, still under reduced motion", () => {
  const walks = [3, 5, 7].map((i) => walkTo(layout.cabinets[i].slug).payload(layout.layoutKey));
  const plans = walks.map((w) => R.plan(w, layout, world, W));
  const list = R.people(plans, 3);
  assert.ok(list.length >= 2);
  for (const q of list) {
    assert.ok(/^replay-\d+$/.test(q.id));
    for (const k of ["x", "z", "yaw", "alpha"]) assert.ok(Number.isFinite(q[k]), k);
    assert.strictEqual(q.color.length, 3);
    assert.ok(q.alpha > 0 && q.alpha <= 0.5);
    assert.strictEqual(q.label, undefined);  // labels are for presence only
  }
  const xs = new Set(list.map((q) => q.x.toFixed(3) + q.z.toFixed(3)));
  assert.strictEqual(xs.size, list.length, "not in lockstep");
  const a = R.people(plans, 1, {reduced: true}), b = R.people(plans, 9, {reduced: true});
  assert.deepStrictEqual(a, b);
  assert.deepStrictEqual(a.map((q) => q.cabinet), [3, 5, 7].map((i) => layout.cabinets[i].slug));
});

if (failures) { console.log(failures + " failed"); process.exit(1); }

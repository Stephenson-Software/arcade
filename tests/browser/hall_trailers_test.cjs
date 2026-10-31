// Unit tests for src/arcade/hall_assets/hall-trailers.js (which screens play
// their trailer), under plain node: node tests/browser/hall_trailers_test.cjs
const assert = require("assert");
const path = require("path");
const T = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-trailers.js"));

let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}

// A row of cabinets along x at z = 0, screens facing +z (angle 0), 1.16 m apart;
// the visitor stands in front of them at z = 2, looking at them (-z: yaw = pi/2).
const row = (n, extra = {}) => [...Array(n)].map((_, k) => Object.assign({x: k * 1.16, z: 0, angle: 0, clip: `clips/${k}.mp4`}, extra));
const facingRow = (x) => ({x, z: 2, yaw: Math.PI / 2});

test("the nearest screens play, nearest first, at most max", () => {
  const cs = row(8);
  assert.deepStrictEqual(T.pick(facingRow(2 * 1.16), cs, {max: 2}).slice(0, 1), [2]);
  const two = T.pick(facingRow(2 * 1.16 + 0.3), cs, {max: 2});
  assert.deepStrictEqual(two, [2, 3]);
  assert.strictEqual(T.pick(facingRow(0), cs, {max: 1}).length, 1);
});

test("none when max is 0 (reduced motion) or nobody stands anywhere", () => {
  assert.deepStrictEqual(T.pick(facingRow(0), row(4), {max: 0}), []);
  assert.deepStrictEqual(T.pick(null, row(4), {max: 2}), []);
});

test("only cabinets with a clip, and lit ones in a filtered hall", () => {
  const cs = row(3);
  cs[0].clip = null; cs[1].lit = false;
  assert.deepStrictEqual(T.pick(facingRow(0), cs, {max: 3}), [2]);
});

test("not from behind the cabinet, nor behind the visitor", () => {
  const cs = row(1);
  // Behind the cabinet (its back), looking at it.
  assert.deepStrictEqual(T.pick({x: 0, z: -2, yaw: -Math.PI / 2}, cs, {max: 1}), []);
  // In front of it but facing away (looking +z).
  assert.deepStrictEqual(T.pick({x: 0, z: 2, yaw: -Math.PI / 2}, cs, {max: 1}), []);
  // Turned a little: still in sight.
  assert.deepStrictEqual(T.pick({x: 0, z: 2, yaw: Math.PI / 2 + 0.8}, cs, {max: 1}), [0]);
});

test("a cabinet turned round (angle pi) shows its screen to the other side", () => {
  const cs = row(1, {angle: Math.PI});
  assert.deepStrictEqual(T.pick({x: 0, z: -2, yaw: -Math.PI / 2}, cs, {max: 1}), [0]);
  assert.deepStrictEqual(T.pick(facingRow(0), cs, {max: 1}), []);
});

test("out of range nothing plays; one playing is kept a little further out", () => {
  const cs = row(1), far = {x: 0, z: T.RANGE + 0.5, yaw: Math.PI / 2};
  assert.deepStrictEqual(T.pick(far, cs, {max: 1}), []);
  assert.deepStrictEqual(T.pick(far, cs, {max: 1, playing: [0]}), [0]);
  assert.deepStrictEqual(T.pick({x: 0, z: T.RANGE + 3, yaw: Math.PI / 2}, cs, {max: 1, playing: [0]}), []);
});

test("the one playing keeps playing when a neighbour is barely nearer (no flicker)", () => {
  const cs = row(2), me = facingRow(1.16 / 2 + 0.05);  // a hair nearer cabinet 1
  assert.deepStrictEqual(T.pick(me, cs, {max: 1}), [1]);
  assert.deepStrictEqual(T.pick(me, cs, {max: 1, playing: [0]}), [0]);
});

if (failures) { console.log(failures + " failed"); process.exit(1); }

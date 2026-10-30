// Unit tests for src/arcade/hall_assets/hall-controls.js (the gamepad),
// under plain node: node tests/browser/hall_controls_test.cjs
const assert = require("assert");
const path = require("path");
const C = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-controls.js"));

let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}
// A "standard" mapping gamepad: 4 axes, 17 buttons.
function gamepad(axes = [0, 0, 0, 0], down = []) {
  return {id: "Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)", connected: true, mapping: "standard",
    axes, buttons: Array.from({length: 17}, (_, i) => ({pressed: down.includes(i), value: down.includes(i) ? 1 : 0}))};
}
const close = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

test("a resting or slightly worn stick reads exactly nothing: no walk, no turn", () => {
  for (const drift of [[0, 0, 0, 0], [0.1, -0.12, 0.08, 0.15], [-0.17, 0, 0, -0.17]]) {
    const p = C.pad(gamepad(drift));
    assert.deepStrictEqual([p.forward, p.right, p.lookX, p.lookY], [0, 0, 0, 0], String(drift));
    assert.strictEqual(p.run, false);
  }
});

test("the left stick walks: up is forward, right is right, full deflection runs", () => {
  let p = C.pad(gamepad([0, -1, 0, 0]));
  assert.ok(close(p.forward, 1) && close(p.right, 0) && p.run);
  p = C.pad(gamepad([0.5, 0, 0, 0]));
  assert.ok(p.right > 0.3 && p.right < 0.5 && p.forward === 0 && !p.run);
  p = C.pad(gamepad([0, 0.6, 0, 0]));
  assert.ok(p.forward < 0);
  // Clicking the stick in runs at any deflection.
  assert.ok(C.pad(gamepad([0, -0.4, 0, 0], [10])).run);
});

test("the d-pad walks too", () => {
  const p = C.pad(gamepad(undefined, [12, 15]));
  assert.strictEqual(p.forward, 1);
  assert.strictEqual(p.right, 1);
  assert.strictEqual(C.pad(gamepad(undefined, [13, 14])).forward, -1);
});

test("the right stick looks, finer near the middle, full rate at the edge", () => {
  const full = C.pad(gamepad([0, 0, 1, 0])), down = C.pad(gamepad([0, 0, 0, 1])), half = C.pad(gamepad([0, 0, 0.6, 0]));
  assert.ok(close(full.lookX, 1) && close(down.lookY, 1));
  assert.ok(half.lookX > 0 && half.lookX < 0.3, String(half.lookX));
  assert.ok(C.pad(gamepad([0, 0, -1, 0])).lookX < 0);
});

test("the dead zone is radial and rescaled: just past it reads small, the edge reads 1", () => {
  const [x0] = C.deadzone(C.DEAD + 0.01, 0);
  assert.ok(x0 > 0 && x0 < 0.02);
  const [x1, y1] = C.deadzone(Math.SQRT1_2, Math.SQRT1_2);
  assert.ok(close(Math.hypot(x1, y1), 1, 1e-6));
});

test("A plays, B goes back, View/Select is read: once each, on the frame they go down", () => {
  const a0 = C.pad(gamepad()), a1 = C.pad(gamepad(undefined, [0])), a2 = C.pad(gamepad(undefined, [0]));
  assert.deepStrictEqual(C.edges(a0, a1), {a: true, b: false, select: false});
  assert.deepStrictEqual(C.edges(a1, a2), {a: false, b: false, select: false});
  assert.deepStrictEqual(C.edges(null, C.pad(gamepad(undefined, [1, 8]))), {a: false, b: true, select: true});
});

test("nothing is read from a missing, disconnected or odd pad", () => {
  for (const gp of [null, undefined, {connected: false, axes: [1, 1, 1, 1], buttons: [1, 1]}, {axes: [NaN, "x"], buttons: []}]) {
    const p = C.pad(gp);
    assert.ok(!p.forward && !p.right && !p.lookX && !p.lookY && !p.a && !p.b, JSON.stringify(gp));
  }
  // Older browsers list buttons as plain numbers.
  assert.ok(C.pad({axes: [], buttons: [1]}).a);
});

test("the first connected pad of a getGamepads() list, and a short name for the toast", () => {
  const gp = gamepad();
  assert.strictEqual(C.first([null, {connected: false}, gp]), gp);
  assert.strictEqual(C.first([]), null);
  assert.strictEqual(C.first(null), null);
  assert.strictEqual(C.name(gp), "Xbox Wireless Controller");
  assert.strictEqual(C.name({id: "054c-0ce6-Wireless Controller"}), "Wireless Controller");
  assert.strictEqual(C.name({id: ""}), "Controller");
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log("all passed");

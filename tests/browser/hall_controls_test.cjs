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

/* ---------------------------------------------------------- settings */
function memoryStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return {getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), map: m};
}
const S = C.settings;

test("the defaults: sensitivity 1, no invert, 62 degree view, head bob off, no reduced motion, hum off", () => {
  const s = S.load(memoryStorage());
  assert.deepStrictEqual(s, {sensitivity: 1, invertY: false, fov: 62, bob: false, reduceMotion: false, hum: false});
});

test("settings are kept and read back as one object", () => {
  const st = memoryStorage();
  assert.strictEqual(S.save(st, {sensitivity: 1.7, invertY: true, fov: 75, bob: true, reduceMotion: true, hum: true}), true);
  assert.deepStrictEqual(JSON.parse(st.map.get(S.KEY)), {sensitivity: 1.7, invertY: true, fov: 75, bob: true, reduceMotion: true, hum: true});
  assert.deepStrictEqual(S.load(st), {sensitivity: 1.7, invertY: true, fov: 75, bob: true, reduceMotion: true, hum: true});
});

test("storage that throws or is missing never breaks the hall: the defaults, and save says no", () => {
  const throwing = {getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceededError"); }};
  assert.deepStrictEqual(S.load(throwing), S.clean({}));
  assert.deepStrictEqual(S.load(null), S.clean({}));
  assert.strictEqual(S.save(throwing, {fov: 80}), false);
  assert.strictEqual(S.save(null, {fov: 80}), false);
});

test("a never-saved setting takes the fallback (the system's reduced motion, the older keys)", () => {
  const s = S.load(memoryStorage(), {reduceMotion: true, bob: true, hum: true});
  assert.ok(s.reduceMotion && s.bob && s.hum);
  // A saved choice wins over the fallback, both ways.
  const st = memoryStorage({[S.KEY]: JSON.stringify({reduceMotion: false, bob: false})});
  const t = S.load(st, {reduceMotion: true, bob: true});
  assert.ok(!t.reduceMotion && !t.bob);
});

test("broken, out-of-range or wrongly typed values are cleaned, not trusted", () => {
  assert.deepStrictEqual(S.load(memoryStorage({[S.KEY]: "{not json"})), S.clean({}));
  const s = S.load(memoryStorage({[S.KEY]: JSON.stringify({sensitivity: 99, fov: -4, invertY: "yes", bob: 1, extra: 5})}));
  assert.strictEqual(s.sensitivity, S.RANGE.sensitivity[1]);
  assert.strictEqual(s.fov, S.RANGE.fov[0]);
  assert.strictEqual(s.invertY, false);
  assert.strictEqual(s.bob, false);
  assert.ok(!("extra" in s));
  assert.strictEqual(S.clean({sensitivity: "1.25", fov: 70.6}).sensitivity, 1.25);
  assert.strictEqual(S.clean({fov: 70.6}).fov, 71);
  assert.strictEqual(S.clean({sensitivity: NaN}).sensitivity, 1);
});

/* ------------------------------------------- keyboard and screen readers */
test("Tab's order is nearest first from where the visitor stands, ties by title", () => {
  const cs = [{title: "Far", x: 0, z: -9}, {title: "Near", x: 1, z: 0}, {title: "Bee", x: 0, z: -3}, {title: "Ant", x: 3, z: 0}];
  assert.deepStrictEqual(C.order({x: 0, z: 0}, cs).map((c) => c.title), ["Near", "Ant", "Bee", "Far"]);
  assert.deepStrictEqual(C.order({x: 0, z: -9}, cs).map((c) => c.title)[0], "Far");
  // Measured to the spot given (a cabinet's front), not its centre.
  const at = (c) => (c.title === "Far" ? [0, 0.5] : [c.x, c.z]);
  assert.strictEqual(C.order({x: 0, z: 0}, cs, at)[0].title, "Far");
  assert.deepStrictEqual(C.order({x: 0, z: 0}, []), []);
});

test("the pointer: a cabinet in sight is marked where it is on screen", () => {
  // Looking along -x (yaw 0), level.
  const view = {x: 0, y: 1.6, z: 0, yaw: 0, pitch: 0, aspect: 16 / 9, fov: 62};
  const ahead = C.project(view, [-5, 1.6, 0]);
  assert.ok(ahead.on && Math.abs(ahead.nx) < 1e-9 && Math.abs(ahead.ny) < 1e-9);
  const up = C.project(view, [-5, 2.6, 0]);
  assert.ok(up.on && up.ny > 0);
  // Screen-right, looking along -x, is -z.
  const right = C.project(view, [-5, 1.6, -1]);
  assert.ok(right.on && right.nx > 0, JSON.stringify(right));
});

test("the pointer: out of sight, it sits at the edge towards the cabinet and the view does not move", () => {
  const view = {x: 0, y: 1.6, z: 0, yaw: 0, pitch: 0, aspect: 16 / 9, fov: 62};
  const before = JSON.stringify(view);
  const side = C.project(view, [0, 1.6, -5]);          // 90 degrees to the right
  assert.ok(!side.on && side.nx > 0.8 && Math.abs(side.angle) < 0.01, JSON.stringify(side));
  const left = C.project(view, [0, 1.6, 5]);
  assert.ok(!left.on && left.nx < -0.8);
  const behind = C.project(view, [5, 1.6, 0]);         // straight back: "turn right"
  assert.ok(!behind.on && behind.nx > 0.8);
  for (const q of [side, left, behind]) assert.ok(Math.max(Math.abs(q.nx), Math.abs(q.ny)) <= 0.9 + 1e-9);
  assert.strictEqual(JSON.stringify(view), before);
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log("all passed");

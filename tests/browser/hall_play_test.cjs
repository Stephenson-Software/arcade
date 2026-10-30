// Unit tests for src/arcade/hall_assets/hall-play.js (the move into a game
// and back), under plain node: node tests/browser/hall_play_test.cjs
const assert = require("assert");
const path = require("path");
const A = path.join(__dirname, "..", "..", "src", "arcade", "hall_assets");
const P = require(path.join(A, "hall-play.js"));
const W = require(path.join(A, "hall-walk.js"));

let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}
const from = {x: 0, y: 1.62, z: 3, yaw: Math.PI / 2, pitch: 0.06};
const to = {x: -2, y: 1.44, z: 0.8, yaw: Math.PI / 2 + 0.4, pitch: 0};
const near = (a, b, eps = 1e-6) => ["x", "y", "z", "yaw", "pitch"].every((k) => Math.abs(a[k] - b[k]) < eps);
// Runs the machine from t0 to t1 (ms) in 1/60 s frames; returns every event and the last update.
function run(m, t0, t1) {
  const events = [];
  let u = null;
  for (let t = t0; t <= t1 + 1e-9; t += 1000 / 60) { u = m.update(t); events.push(...u.events); }
  return {events, u};
}

test("into a framed game: ease in, wait for the paint, crossfade, play", () => {
  const m = P.machine();
  assert.ok(m.start(0, {from, to, how: "frame"}));
  let u = m.update(0);
  assert.deepStrictEqual(u.events, ["load-frame"]);
  assert.ok(near(u.camera, from) && u.locked && u.frame === 0);
  u = m.update(500);
  assert.strictEqual(u.state, "in");
  assert.ok(u.camera.z < from.z && u.camera.z > to.z, "half way");
  // Not painted yet: parked at the screen, the frame still hidden.
  let r = run(m, 520, 3000);
  assert.strictEqual(r.u.state, "wait");
  assert.ok(near(r.u.camera, to) && r.u.frame === 0 && r.u.locked);
  m.loaded(3000);
  u = m.update(3100);
  assert.strictEqual(u.state, "show");
  assert.ok(u.frame > 0 && u.frame < 1);
  r = run(m, 3110, 4000);
  assert.strictEqual(r.u.state, "playing");
  assert.deepStrictEqual(r.events, ["frame-shown"]);
  assert.ok(r.u.frame === 1 && !r.u.locked);
});

test("a game that loads during the move crossfades as soon as the move ends", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  m.update(0);
  m.loaded(300);
  const r = run(m, 16, P.T.in * 1000 + 50);
  assert.strictEqual(r.u.state, "show");
});

test("a game that never says it has painted is shown after WAIT_MAX", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  const r = run(m, 0, (P.T.in + P.WAIT_MAX + P.T.show) * 1000 + 100);
  assert.strictEqual(r.u.state, "playing");
  assert.ok(r.events.includes("frame-shown"));
});

test("Back: the frame fades to the screen, then the camera eases back to where the visitor stood", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  m.loaded(100);
  run(m, 0, 3000);
  m.back(3000);
  let u = m.update(3100);
  assert.strictEqual(u.state, "hide");
  assert.ok(u.frame < 1 && u.frame > 0 && near(u.camera, to) && u.locked);
  let r = run(m, 3116, 3000 + P.T.hide * 1000 + 20);
  assert.deepStrictEqual(r.events, ["unload-frame"]);
  assert.strictEqual(r.u.state, "out");
  r = run(m, r.u ? 3000 + P.T.hide * 1000 + 40 : 0, 3000 + (P.T.hide + P.T.out) * 1000 + 50);
  assert.deepStrictEqual(r.events, ["idle"]);
  assert.strictEqual(r.u.state, "idle");
  assert.ok(!r.u.locked && r.u.camera === null);
  // It ended where it began.
  const m2 = P.machine();
  m2.start(0, {from, to, how: "frame"}); m2.loaded(0); run(m2, 0, 2000); m2.back(2000);
  const last = run(m2, 2000, 2000 + (P.T.hide + P.T.out) * 1000 - 20).u;
  assert.ok(near(last.camera, from, 1e-3), JSON.stringify(last.camera));
});

test("the camera's path is eased: slow at both ends, fast in the middle", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  const d = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
  const at = (t) => m.update(t).camera;
  const start = d(at(0), at(50)), middle = d(at(475), at(525)), end = d(at(950), at(1000));
  assert.ok(middle > 4 * start && middle > 4 * end, JSON.stringify([start, middle, end]));
});

test("Back during the move turns round from where the camera is, with no jump", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  const before = m.update(400).camera;
  m.back(400);
  const u = m.update(400);
  assert.ok(u.events.includes("unload-frame"));
  assert.strictEqual(u.state, "out");
  assert.ok(near(u.camera, before, 1e-6));
  const r = run(m, 416, 400 + P.T.out * 1000 + 20);
  assert.ok(r.events.includes("idle"));
});

test("Esc or a tap skips a move: in goes straight to the screen, out straight to standing", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "frame"});
  m.update(200);
  m.skip(200);
  let u = m.update(216);
  assert.strictEqual(u.state, "wait");
  assert.ok(near(u.camera, to));
  m.loaded(216);
  m.skip(230);  // and the crossfade
  u = m.update(240);
  assert.strictEqual(u.state, "playing");
  m.back(300);
  m.skip(310);  // the fade out
  u = m.update(320);
  assert.strictEqual(u.state, "out");
  m.skip(330);
  u = m.update(340);
  assert.strictEqual(u.state, "idle");
  assert.ok(u.events.includes("idle"));
});

test("a game that opens as its own page: the move, a short fade to dark, then navigate (once)", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "navigate"});
  let r = run(m, 0, P.T.in * 1000 + 100);
  assert.ok(!r.events.includes("load-frame"));
  assert.strictEqual(r.u.state, "leave");
  assert.ok(r.u.fade > 0 && r.u.fade < 1);
  r = run(m, P.T.in * 1000 + 116, 3000);
  assert.deepStrictEqual(r.events, ["navigate"]);
  assert.strictEqual(r.u.fade, 1);
});

test("a game in the other isolation mode: the move, a fade, then the switch; resumed at the screen after", () => {
  const m = P.machine();
  m.start(0, {from, to, how: "switch"});
  const r = run(m, 0, 3000);
  assert.deepStrictEqual(r.events, ["switch"]);
  // The reloaded hall picks up at the screen, coming up from dark.
  const n = P.machine();
  n.resume(10000, {from, to});
  let u = n.update(10000);
  assert.deepStrictEqual(u.events, ["load-frame"]);
  assert.strictEqual(u.state, "wait");
  assert.ok(near(u.camera, to) && u.fade === 1 && u.locked);
  u = n.update(10000 + P.T.resume * 1000 / 2);
  assert.ok(u.fade > 0 && u.fade < 1);
  n.loaded(11000);
  const s = run(n, 11000, 12000);
  assert.strictEqual(s.u.state, "playing");
  assert.strictEqual(s.u.fade, 0);
  // And Back steps out to the place it was played from.
  n.back(12000);
  const b = run(n, 12000, 12000 + (P.T.hide + P.T.out) * 1000 + 50);
  assert.deepStrictEqual(b.events, ["unload-frame", "idle"]);
});

test("under reduced motion the camera never moves and the fades are short", () => {
  const m = P.machine({reduced: true});
  m.start(0, {from, to, how: "frame"});
  let u = m.update(0);
  assert.strictEqual(u.camera, null);
  m.loaded(10);
  const r = run(m, 10, 400);
  assert.strictEqual(r.u.state, "playing");
  assert.ok(r.events.includes("frame-shown"));
  m.back(400);
  const b = run(m, 400, 900);
  assert.deepStrictEqual(b.events, ["unload-frame", "idle"]);
  assert.ok(P.T_REDUCED.show <= 0.25 && P.T_REDUCED.hide <= 0.25);
});

test("a second play while one is under way is refused", () => {
  const m = P.machine();
  assert.ok(m.start(0, {from, to, how: "frame"}));
  assert.ok(!m.start(10, {from, to, how: "navigate"}));
  assert.strictEqual(m.how, "frame");
});

test("the screen pose is square-on and the screen covers the view, landscape and portrait", () => {
  const screen = [-0.42, 1.20, 0.42, 1.68, 0.305];
  for (const c of [{x: -2.14, z: -0.72, angle: 0}, {x: 3.3, z: -1.7, angle: Math.PI}, {x: 0, y: 0.45, z: -11.86, angle: 0}]) {
    const fr = W.frame(c);
    for (const aspect of [16 / 9, 390 / 844]) {
      const p = P.screenPose(fr, screen, aspect, 62);
      // Looking straight at the screen's centre: along -f.
      const look = [-Math.cos(p.yaw), -Math.sin(p.yaw)];
      assert.ok(Math.abs(look[0] + fr.f[0]) < 1e-9 && Math.abs(look[1] + fr.f[2]) < 1e-9);
      const centre = fr.p(0, 1.44, 0.305);
      assert.ok(Math.abs(p.y - centre[1]) < 1e-9 && p.pitch === 0);
      const d = Math.hypot(p.x - centre[0], p.z - centre[2]);
      const t = Math.tan(31 * Math.PI / 180);
      // The screen's edges are at or beyond the view's in both directions.
      assert.ok(0.42 / (d * t * aspect) >= 1 - 1e-9 && 0.24 / (d * t) >= 1 - 1e-9, `${aspect}: ${d}`);
      // And close: one of them only just.
      assert.ok(Math.min(0.42 / (d * t * aspect), 0.24 / (d * t)) < 1.1);
    }
  }
});

process.exit(failures ? 1 : 0);

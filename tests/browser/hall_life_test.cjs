// Unit tests for src/arcade/hall_assets/hall-life.js (attract mode, glow,
// sound), under plain node: node tests/browser/hall_life_test.cjs
const assert = require("assert");
const path = require("path");
const L = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-life.js"));

let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}

test("one screen at a time shows its title card, for SHOW seconds in every PERIOD", () => {
  const n = 31, dt = 0.05;
  let shown = 0, steps = 0, swaps = 0, last = -2;
  for (let t = 0; t < 600; t += dt) {
    const k = L.attract(t, n);
    assert.ok(k === -1 || (k >= 0 && k < n));
    if (k >= 0) shown++;
    if (k !== last) swaps++;
    last = k; steps++;
  }
  const duty = shown / steps;
  assert.ok(Math.abs(duty - L.SHOW / L.PERIOD) < 0.02, `duty ${duty}`);
  // Each swap is a title card shown then the poster back: twice per period at most.
  assert.ok(swaps <= 2 * 600 / L.PERIOD + 2, `swaps ${swaps}`);
});

test("over a few minutes most cabinets get a turn, and not the same one twice running", () => {
  const n = 31, seen = new Set();
  let prev = -1;
  for (let k = 0; k < 60; k++) {
    const c = L.attract(k * L.PERIOD + 0.1, n);
    seen.add(c);
    assert.notStrictEqual(c, prev, `turn ${k}`);
    prev = c;
  }
  assert.ok(seen.size > 20, `only ${seen.size}`);
  assert.strictEqual(L.attract(1, 0), -1);
});

test("the shimmer and the glow stay subtle", () => {
  for (let t = 0; t < 60; t += 0.037) for (let i = 0; i < 31; i++) {
    const f = L.flicker(t, i), p = L.pulse(t, i);
    assert.ok(f >= 0.899 && f <= 1.0001, `flicker ${f}`);
    assert.ok(p >= 0.699 && p <= 1.3001, `pulse ${p}`);
  }
  // Neighbours are out of step.
  assert.notStrictEqual(L.flicker(3, 0).toFixed(4), L.flicker(3, 1).toFixed(4));
});

test("scanlines darken every third row and nothing else", () => {
  const w = 4, h = 7, px = new Uint8ClampedArray(w * h * 4).fill(200);
  L.scanlines(px, w, h);
  for (let y = 0; y < h; y++) {
    const v = px[y * w * 4], a = px[y * w * 4 + 3];
    assert.strictEqual(v, y % 3 === 0 ? 172 : 200, `row ${y}`);
    assert.strictEqual(a, 200, "alpha untouched");
  }
});

test("the sound is off until turned on, and without WebAudio stays off quietly", () => {
  const h = L.hum();
  assert.strictEqual(h.on, false);
  assert.strictEqual(h.running, false);
  assert.strictEqual(h.set(true), false);  // no AudioContext under node
  assert.strictEqual(h.on, false);
  h.pause(true); h.pause(false);
});

process.exit(failures ? 1 : 0);

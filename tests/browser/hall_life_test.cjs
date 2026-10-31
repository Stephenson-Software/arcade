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

test("a jack-o'-lantern's flame flickers, never goes out, and each its own way", () => {
  let lo = 1, hi = 0, dips = 0, prev = 1;
  for (let t = 0; t < 60; t += 1 / 12) {
    const f = L.candle(t, 0);
    assert.ok(f >= 0.619 && f <= 1.0001, `candle ${f}`);
    lo = Math.min(lo, f); hi = Math.max(hi, f);
    if (prev - f > 0.08) dips++;
    prev = f;
  }
  // Visibly alive at the hall's 12 Hz life step, not a slow breathe.
  assert.ok(hi - lo > 0.25 && dips > 60, `range ${lo}..${hi}, dips ${dips}`);
  assert.notStrictEqual(L.candle(5, 0).toFixed(3), L.candle(5, 1).toFixed(3));
});

test("each cabinet's loop is its own, the same every visit, and flavoured by its game", () => {
  const a = L.tune({slug: "apex"}), b = L.tune({slug: "apex"}), c = L.tune({slug: "orrery"});
  assert.deepStrictEqual(a, b);
  assert.notDeepStrictEqual(a.notes, c.notes);
  const text = L.tune({slug: "tidewater", engine: "tak"});
  assert.strictEqual(text.wave, "triangle");
  assert.ok(text.bpm < 95, `text bpm ${text.bpm}`);
  assert.deepStrictEqual(text.scale.slice(0, 3), [0, 3, 5], "minor");
  assert.deepStrictEqual(L.tune({slug: "familiar", tags: ["halloween"]}).scale.slice(0, 3), [0, 3, 5]);
  const slugs = ["apex", "roam", "orrery", "kindling", "sisyphus", "steading", "atman", "microbiome", "ophidian", "interakt"];
  const waves = new Set(slugs.map((s) => L.tune({slug: s}).wave));
  assert.ok(waves.size >= 2, "more than one flavour");
  for (const s of slugs.concat(["tidewater", "fishe", ""])) {
    const t = L.tune({slug: s, engine: s === "fishe" ? "tak" : "other"});
    assert.strictEqual(t.notes.length, 32);
    assert.strictEqual(t.notes[0], 0, "starts on the root");
    const sounding = t.notes.filter((n) => n >= 0).length;
    assert.ok(sounding >= 3 && sounding <= 24, `${s}: ${sounding} notes`);
    for (let k = 0; k < 32; k++) {
      const hz = L.noteHz(t, k);
      assert.ok(hz === 0 || (hz > 50 && hz < 2000), `${s} note ${k}: ${hz}`);
    }
    assert.ok(t.bpm >= 70 && t.bpm <= 140);
  }
});

test("a cabinet is heard louder near, to its side, muffled from behind, and not across the hall", () => {
  const cab = {x: 0, z: 0, angle: 0};  // screen (and speaker) faces +z
  const front = (d, yaw = Math.PI / 2) => L.spatial({x: 0, z: 0.4 + d, yaw}, cab);
  assert.ok(front(1).gain > front(3).gain && front(3).gain > front(6).gain);
  assert.ok(front(0.6).gain > 0.85 && front(0.6).gain <= 1);
  assert.strictEqual(front(L.HEAR + 0.1).gain, 0);
  assert.ok(Math.abs(front(2).pan) < 1e-9, "dead ahead is centred");
  // Standing in front, looking along -x (yaw 0): the cabinet is on the right.
  assert.ok(L.spatial({x: 0, z: 2, yaw: 0}, cab).pan > 0.5);
  assert.ok(L.spatial({x: 0, z: 2, yaw: Math.PI}, cab).pan < -0.5);
  // From behind its back, as far from its speaker: quieter and muffled.
  const behind = L.spatial({x: 0, z: -1.6, yaw: -Math.PI / 2}, cab);
  assert.strictEqual(behind.muffle, 1);
  assert.ok(behind.gain < front(2).gain * 0.6, `behind ${behind.gain}`);
  assert.strictEqual(front(2).muffle, 0);
});

test("without WebAudio the cabinets are silent too, and say so", () => {
  const h = L.hum();
  assert.strictEqual(h.cabinets([{id: "apex", tune: L.tune({slug: "apex"}), gain: 1, pan: 0, muffle: 0}]), 0);
  assert.deepStrictEqual(h.voices, []);
});

process.exit(failures ? 1 : 0);

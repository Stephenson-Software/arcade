// Unit tests for src/arcade/hall_assets/hall-people.js and hall-presence.js
// (people in the hall: figures, easing, budget, labels; the presence client's
// parsing, rounding and polling), under plain node. tests/test_hall.py runs
// it with a layout from arcade.hall:
//   node tests/browser/hall_people_test.cjs <layout.json>
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const dir = path.join(__dirname, "..", "..", "src", "arcade", "hall_assets");
const P = require(path.join(dir, "hall-people.js"));
const S = require(path.join(dir, "hall-presence.js"));
const C = require(path.join(dir, "hall-controls.js"));
const W = require(path.join(dir, "hall-walk.js"));

const layout = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;
const view = (o) => Object.assign({x: 0, y: W.EYE, z: 6, yaw: Math.PI / 2, pitch: 0, fov: 62, aspect: 1.6, project: C.project}, o);
const person = (id, x, z, extra) => Object.assign({id, x, z, yaw: 0, color: [0.5, 0.7, 1], alpha: 1}, extra);

test("a layout key is stable, 16 hex digits, and changes with the cabinet order", () => {
  const k = P.layoutKey(["roam", "apex", "kindling"]);
  assert.match(k, /^[0-9a-f]{16}$/);
  assert.strictEqual(P.layoutKey(["roam", "apex", "kindling"]), k);
  assert.notStrictEqual(P.layoutKey(["apex", "roam", "kindling"]), k);
  assert.notStrictEqual(P.layoutKey(["roam", "apex"]), k);
  assert.match(P.layoutKey([]), /^[0-9a-f]{16}$/);
});

test("an id's colour is fixed, in range, and bright", () => {
  for (const id of ["a", "b", "k3x9", "someone-else", "7"]) {
    const c = P.colorOf(id);
    assert.deepStrictEqual(P.colorOf(id), c);
    assert.strictEqual(c.length, 3);
    assert.ok(c.every((v) => v >= 0 && v <= 1));
    assert.ok(Math.max(...c) > 0.75, `bright: ${c}`);
  }
  assert.notDeepStrictEqual(P.colorOf("a"), P.colorOf("b"));
});

test("malformed people are dropped and labels are cleaned", () => {
  assert.strictEqual(P.clean(null), null);
  assert.strictEqual(P.clean({id: "", x: 0, z: 0}), null);
  assert.strictEqual(P.clean({id: "a", x: NaN, z: 0}), null);
  const p = P.clean({id: "a", x: 1, z: 2, label: "  Ada\u0007 Lovelace with a very long name indeed  ", cabinet: "Not A Slug", alpha: 3});
  assert.strictEqual(p.label, "Ada Lovelace with a very long na");
  assert.strictEqual(p.cabinet, null);
  assert.strictEqual(p.alpha, 1);
  assert.deepStrictEqual(p.color, P.colorOf("a"));
});

test("a figure glides between updates over the layer's interval, and faces where it walks", () => {
  const c = P.crowd();
  c.set("ghosts", [person("g", 0, 0)], 0);
  c.set("ghosts", [person("g", 0, 0)], 1);
  c.set("ghosts", [person("g", 1, 0)], 2);  // every ~1 s: eased over ~1.05 s
  c.frame(view(), 2);
  const mid = c.figure("ghosts", "g", 2.525);
  assert.ok(near(mid.x, 0.5, 1e-3), `halfway: ${mid.x}`);
  for (let t = 2.5; t < 3; t += 1 / 60) c.frame(view({reduced: true}), t);
  // Walking towards +x: looking along (-cos yaw, -sin yaw) = (1, 0), so yaw = pi.
  assert.ok(near(Math.abs(c.figure("ghosts", "g", 3).yaw % (2 * Math.PI)), Math.PI, 1e-3), "faces +x");
  assert.ok(near(c.figure("ghosts", "g", 4).x, 1), "arrives");
});

test("a long jump is a teleport, not a slide across the hall", () => {
  const c = P.crowd();
  c.set("replays", [person("r", 0, 0)], 0);
  c.set("replays", [person("r", 10, 0)], 1);
  assert.ok(near(c.figure("replays", "r", 1).x, 10));
});

test("standing at a cabinet: beside its front, facing it, the visitor's spot left clear", () => {
  const c = P.crowd();
  c.setLayout(layout);
  const cab = layout.cabinets[3];
  c.set("presence", [person("b", 0, 0, {cabinet: cab.slug}), person("a", 0, 0, {cabinet: cab.slug}),
    person("z", 0, 0, {cabinet: "no-such-game"})], 0);
  const a = c.figure("presence", "a", 0), b = c.figure("presence", "b", 0), mine = W.front(cab, 1.15);
  assert.ok(a.atCabinet && b.atCabinet);
  assert.ok(near(a.yaw, mine.yaw), "facing the cabinet");
  assert.ok(Math.hypot(a.x - b.x, a.z - b.z) > 1, "two people, two spots");
  for (const f of [a, b]) {
    assert.ok(Math.hypot(f.x - mine.x, f.z - mine.z) > 0.7, "not where the visitor stands");
    assert.ok(Math.hypot(f.x - cab.x, f.z - cab.z) < 2.2, "at the cabinet");
  }
  const z = c.figure("presence", "z", 0);
  assert.ok(!z.atCabinet && near(z.x, 0) && near(z.z, 0), "an unknown cabinet: where they said they were");
});

test("a figure left out fades away and is forgotten", () => {
  const c = P.crowd();
  c.set("ghosts", [person("g", 0, 2)], 0);
  c.frame(view(), 1);
  c.set("ghosts", [], 1);
  assert.ok(c.figure("ghosts", "g", 1).leaving);
  const fading = c.frame(view(), 1.2).poses[0][6];
  assert.ok(fading > 0 && fading < 1, "still fading");
  const out = c.frame(view(), 2);
  assert.deepStrictEqual(out.poses.map((r) => r[6]), [0]);
  assert.ok(out.changed, "the frame after the last figure clears what was drawn");
  assert.strictEqual(c.size, 0);
  assert.ok(!c.frame(view(), 2.1).changed, "and then nothing to upload");
});

test("live people are solid, with eyes; ghosts are translucent meshes; detail drops with distance", () => {
  const c = P.crowd();
  c.set("presence", [person("p", 0, 2)], 0);
  c.set("ghosts", [person("g", 1, 2, {alpha: 0.6})], 0);
  let out = c.frame(view(), 5);
  assert.strictEqual(out.items.length, 4, "body, head, two eyes");
  assert.ok(out.items.every((r) => r.length === 10 && (r[0] === 1 || r[0] === 3)));
  assert.ok(out.points.every((r) => r.length === 9 && r[8] > 0 && r[8] <= 1));
  assert.strictEqual(out.builds.length, 1, "one ghost mesh, built once");
  assert.strictEqual(out.builds[0].slot, P.MESH_SLOT);
  assert.deepStrictEqual(out.poses.map((r) => [r[0], r[1], r[3], r[6]]), [[P.MESH_SLOT, 1, 2, 0.59375]]);
  assert.ok(out.poses[0][2] > 0.04, "it hovers");
  out = c.frame(view(), 5.1);
  assert.strictEqual(out.builds.length, 0, "and then only moved");
  assert.strictEqual(out.poses.length, 1);
  c.set("presence", [person("p", 0, -8)], 5);   // 14 m away: no eyes
  c.set("ghosts", [person("g", 1, -20)], 5);    // 26 m away: still a ghost
  out = c.frame(view(), 10);
  assert.strictEqual(out.items.length, 2);
  assert.strictEqual(out.poses.length, 1);
  c.set("presence", [person("p", 0, -40)], 10);  // beyond 30 m: nothing
  c.set("ghosts", [], 10);
  out = c.frame(view(), 15);
  assert.strictEqual(out.items.length + out.points.length, 0);
  assert.deepStrictEqual(out.poses.map((r) => r[6]), [0], "its slot is put away");
  assert.deepStrictEqual(c.frame(view(), 15.1).poses, [], "once");
});

test("a live person fades in as a translucent copy of themselves, then is solid", () => {
  const c = P.crowd();
  c.set("presence", [person("p", 0, 2)], 0);
  let out = c.frame(view(), 0.2);
  assert.strictEqual(out.items.length, 0);
  assert.strictEqual(out.builds.length, 1);
  assert.ok(out.poses[0][6] > 0 && out.poses[0][6] < 1);
  out = c.frame(view(), 1);
  assert.strictEqual(out.items.length, 4);
  assert.deepStrictEqual(out.poses.map((r) => r[6]), [0]);
});

test("the figure meshes are well formed, round the origin, looking along -x", () => {
  for (const m of [P.ghostMesh([0.5, 0.8, 1]), P.personMesh([1, 0.5, 0.3])]) {
    const nv = m.positions.length / 3;
    assert.ok(Number.isInteger(nv) && nv > 50 && nv < 2000, `vertices ${nv}`);
    assert.strictEqual(m.normals.length, m.positions.length);
    assert.strictEqual(m.colors.length, m.positions.length);
    assert.strictEqual(m.uvs.length, 0);
    assert.ok(m.indices.length % 3 === 0 && m.indices.every((i) => i >= 0 && i < nv));
    for (let i = 0; i < m.normals.length; i += 3) {
      assert.ok(near(Math.hypot(m.normals[i], m.normals[i + 1], m.normals[i + 2]), 1, 1e-6));
    }
    const ys = m.positions.filter((_, i) => i % 3 === 1);
    assert.ok(Math.min(...ys) >= 0 && Math.max(...ys) < 1.6);
    // The eyes (the dark or white vertices at eye height) are on the -x side.
    const eyes = [];
    for (let i = 0; i < nv; i++) {
      const col = m.colors.slice(3 * i, 3 * i + 3);
      if (col.every((v) => v > 0.99) || Math.max(...col) < 0.2) eyes.push(m.positions[3 * i]);
    }
    assert.ok(eyes.length > 10 && eyes.every((x) => x < -0.1), `eyes at ${Math.max(...eyes)}`);
  }
});

test("the budget: 12 (6 on a phone), presence first, then replays, then ghosts, nearest first", () => {
  const c = P.crowd();
  const row = (n, z, pre) => Array.from({length: n}, (_, i) => person(pre + i, -4 + i * 0.5, z));
  c.set("ghosts", row(10, 4, "g"), 0);      // the nearest
  c.set("replays", row(5, 0, "r"), 0);
  c.set("presence", row(4, -6, "p"), 0);    // the furthest
  c.frame(view(), 5);
  assert.deepStrictEqual(c.stats.layers, {presence: 4, replays: 5, ghosts: 3});
  assert.strictEqual(c.stats.drawn, 12);
  c.frame(view({lite: true}), 5.1);
  assert.deepStrictEqual(c.stats.layers, {presence: 4, replays: 2, ghosts: 0});
});

test("a figure at the eye fades out, so the view is never inside one", () => {
  const c = P.crowd();
  c.set("presence", [person("p", 0.1, 6)], 0);
  const out = c.frame(view(), 5);
  assert.strictEqual(out.items.length + out.points.length, 0);
});

test("reduce motion: no bob and no sway", () => {
  const c = P.crowd();
  c.set("presence", [person("p", 0, 2)], 0);
  const a = c.frame(view({reduced: true}), 5).items[1][2], b = c.frame(view({reduced: true}), 5.37).items[1][2];
  assert.strictEqual(a, b);
  const d = c.frame(view(), 6).items[1][2], e = c.frame(view(), 6.37).items[1][2];
  assert.notStrictEqual(d, e, "it does breathe otherwise");
});

test("labels: presence only, in view, nearest six (three on a phone), within 14 m", () => {
  const c = P.crowd();
  // The view looks along -z (yaw pi/2) from z = 6.
  const ps = Array.from({length: 9}, (_, i) => person("p" + i, (i % 3 - 1) * 0.8, 3 - i * 0.6, {label: "N" + i}));
  ps.push(person("behind", 0, 9, {label: "Behind"}), person("far", 0, -12, {label: "Far"}));
  c.set("presence", ps, 0);
  c.set("ghosts", [person("g", 0, 2, {label: "Ghost"})], 0);
  let out = c.frame(view(), 5);
  assert.deepStrictEqual(out.labels.map((l) => l.text), ["N0", "N1", "N2", "N3", "N4", "N5"]);
  assert.ok(out.labels.every((l) => Math.abs(l.nx) <= 1.05 && l.ny > 0 && l.opacity > 0));
  out = c.frame(view({lite: true}), 5.1);
  assert.strictEqual(out.labels.length, 3);
});

test("a hidden layer draws nothing until shown again", () => {
  const c = P.crowd();
  c.set("presence", [person("p", 0, 2, {label: "A"})], 0);
  c.hide("presence", true);
  assert.ok(c.hidden("presence"));
  let out = c.frame(view(), 5);
  assert.strictEqual(out.items.length + out.labels.length, 0);
  c.hide("all", false);
  out = c.frame(view(), 5.1);
  assert.ok(out.items.length > 0);
});

/* --------------------------------------------- a tap on a figure */
// The screen point of a world point under view(), as the page passes it to pick().
const at = (v, p) => C.project(v, p, 50);
test("pick: the figure under a point, nearest first, and nothing beside it", () => {
  const c = P.crowd();
  c.set("presence", [person("near", 0, 3, {label: "Near"}), person("far", 0, -4, {label: "Far"})], 0);
  c.set("ghosts", [person("g", 2.5, 1)], 0);
  const v = view({height: 720});
  c.frame(v, 5);
  // On the body of the near one (the far one is straight behind it): the near one.
  let q = at(v, [0, 0.9, 3]);
  assert.deepStrictEqual((({layer, id}) => ({layer, id}))(c.pick(v, q.nx, q.ny, 18)), {layer: "presence", id: "near"});
  assert.ok(c.pick(v, q.nx, q.ny, 18).dist < 4);
  // Its head, too; and the ghost, hovering.
  q = at(v, [0, 1.45, 3]);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 18).id, "near");
  q = at(v, [2.5, 0.7, 1]);
  assert.deepStrictEqual(c.pick(v, q.nx, q.ny, 18).layer, "ghosts");
  // Well beside every figure, and above the near one's head: nothing.
  q = at(v, [-2, 0.9, 3]);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 18), null);
  q = at(v, [0, 2.6, 3]);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 18), null);
  // A wider hit radius reaches a figure a little to the side.
  q = at(v, [0.5, 0.9, 3]);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 4), null);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 120).id, "near");
  // A hidden layer is not drawn, so it cannot be picked.
  c.hide("ghosts", true);
  c.frame(v, 5.1);
  q = at(v, [2.5, 0.7, 1]);
  assert.strictEqual(c.pick(v, q.nx, q.ny, 18), null);
  // The pure function, for nothing drawn or no projection.
  assert.strictEqual(P.pickFigure([], v, 0, 0, 18), null);
  assert.strictEqual(P.pickFigure([{layer: "ghosts", id: "x", x: 0, y: 0, z: 3}], Object.assign({}, v, {project: null}), 0, 0, 18), null);
});

test("reveal: a tapped figure's caption, beyond the labels' range and count, for a few seconds", () => {
  const c = P.crowd();
  // Seven named people nearby (six labels at most), one named far away (past 14 m), a ghost and a replay.
  const ps = Array.from({length: 7}, (_, i) => person("p" + i, (i % 3 - 1) * 0.8, 3 - i * 0.6, {label: "N" + i}));
  ps.push(person("far", 0, -14, {label: "Faraway"}));
  c.set("presence", ps, 0);
  c.set("ghosts", [person("g", 2, -2, {label: "ignored"})], 0);
  c.set("replays", [person("r", -2, -2)], 0);
  let out = c.frame(view(), 5);
  assert.ok(!out.labels.some((l) => l.text === "Faraway"), "too far for a label of its own");
  assert.ok(!out.labels.some((l) => l.text === "N6"), "past the six");
  c.reveal("presence", "far", 5);
  out = c.frame(view(), 5.1);
  const far = out.labels.find((l) => l.text === "Faraway");
  assert.ok(far && far.pinned && far.opacity >= 0.6, JSON.stringify(out.labels));
  assert.strictEqual(out.labels.filter((l) => !l.pinned).length, 6, "the usual six stay");
  // A tap on someone else replaces it; a ghost and a replay say only what they are.
  c.reveal("ghosts", "g", 5.2);
  out = c.frame(view(), 5.3);
  assert.deepStrictEqual(out.labels.filter((l) => l.pinned).map((l) => [l.text, l.layer]), [["A recent visitor", "ghosts"]]);
  c.reveal("replays", "r", 5.4);
  out = c.frame(view(), 5.5);
  assert.deepStrictEqual(out.labels.filter((l) => l.pinned).map((l) => l.text), ["A walk from today"]);
  assert.deepStrictEqual(c.revealed, ["replays:r"]);
  // Gone after four seconds; the usual labels are untouched.
  out = c.frame(view(), 9.5);
  assert.strictEqual(out.labels.filter((l) => l.pinned).length, 0);
  assert.deepStrictEqual(c.revealed, []);
  assert.deepStrictEqual(out.labels.map((l) => l.text), ["N0", "N1", "N2", "N3", "N4", "N5"]);
  // On a phone: three of the usual, and the one asked for besides.
  c.reveal("presence", "p4", 9.6);
  out = c.frame(view({lite: true}), 9.7);
  assert.strictEqual(out.labels.length, 4);
  assert.ok(out.labels.some((l) => l.text === "N4" && l.pinned));
});

test("hover: the caption while the mouse is over a figure, and not after", () => {
  const c = P.crowd();
  c.set("ghosts", [person("g", 0, 2)], 0);
  let out = c.frame(view(), 5);
  assert.strictEqual(out.labels.length, 0, "a ghost has no label of its own");
  c.hover({layer: "ghosts", id: "g"}, 5);
  out = c.frame(view(), 60);
  assert.deepStrictEqual(out.labels.map((l) => l.text), ["A recent visitor"]);
  c.hover(null, 60);
  out = c.frame(view(), 60.1);
  assert.strictEqual(out.labels.length, 0);
  assert.deepStrictEqual(P.CAPTION, {ghosts: "A recent visitor", replays: "A walk from today"});
});

/* ---------------------------------------------------- hall-presence.js */
test("the presence list keeps well-formed people only", () => {
  const body = {people: [
    {id: "s1", name: "Ada", x: 1, z: -2, yaw: 1, cabinet: "roam"},
    {id: "s2", name: "  Bo\u0000 ", x: 0, z: 0, cabinet: "<script>"},
    {id: "", name: "x", x: 0, z: 0},
    {id: "s3", x: "1", z: 0},
    {id: "s4", x: 1e9, z: 0},
    null,
  ], ttl: 10};
  assert.deepStrictEqual(S.parse(body), [
    {id: "s1", name: "Ada", x: 1, z: -2, yaw: 1, cabinet: "roam", you: false},
    {id: "s2", name: "Bo", x: 0, z: 0, yaw: 0, cabinet: null, you: false},
  ]);
  assert.deepStrictEqual(S.parse(null), []);
  assert.deepStrictEqual(S.parse({people: "no"}), []);
});

test("presence people become labelled figures in their own colour", () => {
  const f = S.figures([{id: "s1", name: "Ada", x: 1, z: 2, yaw: 0.5, cabinet: "roam"}, {id: "s2", name: "", x: 0, z: 0, yaw: 0, cabinet: null}], P.colorOf);
  assert.strictEqual(f[0].label, "Ada");
  assert.deepStrictEqual(f[0].color, P.colorOf("s1"));
  assert.strictEqual(f[0].cabinet, "roam");
  assert.strictEqual(f[1].label, "Player");
  assert.strictEqual(f[1].cabinet, undefined);
});

test("the pose sent is coarse: 0.25 m and 10 degrees", () => {
  const p = S.pose({x: 1.13, z: -6.62, yaw: 0.2}, "roam", "k");
  assert.deepStrictEqual(Object.keys(p).sort(), ["cabinet", "layout", "x", "yaw", "z"]);
  assert.strictEqual(p.x, 1.25);
  assert.strictEqual(p.z, -6.5);
  assert.ok(near(p.yaw, Math.PI / 18, 1e-3));
  assert.ok(S.pose({x: 0, z: 0, yaw: -0.1}, null, "k").yaw >= 0);
  assert.strictEqual(S.pose({x: 0, z: 0, yaw: 0}, "Bad Slug", "k").cabinet, null);
  assert.strictEqual(S.pose(null, null, "k"), null);
  assert.strictEqual(S.pose({x: 0, z: 0}, null, null), null);
});

test("polling: every second with company, every ten alone, three at least when saving data", () => {
  assert.strictEqual(S.delay({anyone: true}), 1000);
  assert.strictEqual(S.delay({anyone: false}), 10000);
  assert.strictEqual(S.delay({anyone: true, saveData: true}), 3000);
  assert.strictEqual(S.delay({anyone: false, saveData: true}), 10000);
});

test("the visitor never sees their own figure", () => {
  const list = [{id: "a", x: 1, z: 2, cabinet: null}, {id: "b", x: 3, z: 4, cabinet: "roam"},
    {id: "c", x: 5, z: 5, cabinet: null, you: true}, {id: "d", x: 7, z: 7, cabinet: null}];
  const sent = [{x: 3, z: 4, cabinet: "roam"}];
  assert.deepStrictEqual(S.notMe(list, sent, "d").map((p) => p.id), ["a"]);
  assert.deepStrictEqual(S.notMe(list, [], null).map((p) => p.id), ["a", "b", "d"]);
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }

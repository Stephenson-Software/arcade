// Unit tests for src/arcade/hall_assets/hall-fame.js (warm marquees, the Hall
// of Fame board), under plain node: node tests/browser/hall_fame_test.cjs
const assert = require("assert");
const path = require("path");
const F = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-fame.js"));

let failures = 0;
async function test(name, fn) {
  try { await fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}

(async () => {
  await test("only the most played and liked marquees warm up, the most the warmest", () => {
    const plays = {tidewater: 304, "env-lib-cpp": 396, roam: 228, apex: 229, dice: 135, cave: 50, quiet: 0};
    const w = F.warmth(plays, {});
    assert.strictEqual(w["env-lib-cpp"], 1);
    assert.ok(w.tidewater > 0.3 && w.tidewater < 1, JSON.stringify(w));
    // The middle of the field stays as it was.
    assert.strictEqual(w.roam, 0); assert.strictEqual(w.cave, 0); assert.strictEqual(w.quiet, 0);
    for (const v of Object.values(w)) assert.ok(v >= 0 && v <= 1);
    // Likes lift a cabinet: roam with the most likes overtakes apex (one more play).
    const liked = F.warmth(plays, {roam: 29, apex: 1});
    assert.ok(liked.roam > 0.1 && liked.apex === 0, JSON.stringify(liked));
    // A handful of likes hardly moves anything; a like alone, with no plays, does not glow.
    const few = F.warmth(plays, {roam: 1, apex: 1});
    assert.ok(few["env-lib-cpp"] > 0.9 && few.tidewater > 0.3 && few.roam < 0.05, JSON.stringify(few));
    assert.strictEqual(F.warmth({a: 300, b: 0}, {b: 40}).b, 0);
    assert.deepStrictEqual(F.warmth({}, {}), {});
    assert.deepStrictEqual(F.warmth(null, null), {});
    // Bad numbers are nothing.
    assert.strictEqual(F.warmth({a: 10, b: -5, c: NaN}, {a: "x"}).b, 0);
  });

  await test("values read with their units", () => {
    assert.strictEqual(F.valueText({integer: true, unit: "days"}, 12), "12 days");
    assert.strictEqual(F.valueText({integer: true, unit: "days"}, 1), "1 day");
    assert.strictEqual(F.valueText({integer: true, unit: "wins"}, 1024), "1,024 wins");
    assert.strictEqual(F.valueText({unit: "seconds"}, 4.54), "4.5 seconds");
    assert.strictEqual(F.valueText({}, NaN), "");
  });

  const cabs = [{slug: "roam", title: "Roam"}, {slug: "rock-paper-scissors", title: "Rock Paper Scissors"},
    {slug: "frog-hopper", title: "Frog Hopper"}];
  await test("the board lists each board's champion, the hall's order, at most MAX", () => {
    const found = [
      {slug: "frog-hopper", board: {id: "fastest-crossing", title: "Fastest crossing", unit: "seconds"}, top: {displayName: "Ann", value: 7.25}},
      {slug: "roam", board: {id: "most-days", title: "Most days in one world", unit: "days", integer: true}, top: {displayName: "Bo", value: 40}},
      {slug: "roam", board: {id: "most-rooms", title: "Most rooms", integer: true}, top: null},
      {slug: "gone", board: {id: "x", title: "X"}, top: {displayName: "Cy", value: 1}},
      {slug: "rock-paper-scissors", board: {id: "best-streak", title: "Best streak", unit: "wins", integer: true}, top: {displayName: "", value: 3}},
    ];
    assert.deepStrictEqual(F.champions(found, cabs), [
      {game: "Roam", board: "Most days in one world", name: "Bo", value: "40 days"},
      {game: "Frog Hopper", board: "Fastest crossing", name: "Ann", value: "7.3 seconds"},
    ]);
    const many = [...Array(10)].map((_, k) => ({slug: "roam", board: {id: "b" + k, title: "B" + k}, top: {displayName: "P" + k, value: k}}));
    assert.strictEqual(F.champions(many, cabs).length, F.MAX);
    assert.ok(F.champions([{slug: "roam", board: {id: "b", title: "B"}, top: {displayName: "x".repeat(60), value: 1}}], cabs)[0].name.length <= 20);
    assert.deepStrictEqual(F.champions(null, cabs), []);
  });

  // A fake arcade-social, and a sessionStorage, for load().
  function fakeFetch(routes, seen) {
    return async (url, opts) => {
      seen.push([url, opts && opts.credentials]);
      const body = routes[url.replace("https://api.example", "")];
      if (body === undefined) return {ok: false, json: async () => ({})};
      return {ok: true, json: async () => body};
    };
  }
  function store() { const m = new Map(); return {getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v))}; }
  const deployed = cabs.map((c) => Object.assign({deployed: true}, c)).concat([{slug: "soon", title: "Soon", deployed: false}]);

  await test("load asks for each deployed game's boards, then each board's top, without credentials, once a session", async () => {
    const seen = [], s = store();
    globalThis.fetch = fakeFetch({
      "/v1/games/roam/boards": {boards: [{id: "most-days", title: "Most days", unit: "days", integer: true}, {id: "../x"}]},
      "/v1/games/rock-paper-scissors/boards": {boards: []},
      "/v1/games/frog-hopper/boards": {boards: [{id: "fastest-crossing", title: "Fastest crossing"}]},
      "/v1/boards/roam/most-days?limit=1": {entries: [{displayName: "Bo", value: 40, rank: 1}]},
      "/v1/boards/frog-hopper/fastest-crossing?limit=1": {entries: []},
    }, seen);
    const doc = await F.load("https://api.example", deployed, s);
    assert.deepStrictEqual(doc.games, ["roam", "frog-hopper"]);
    assert.strictEqual(doc.off, false);
    assert.deepStrictEqual(F.champions(doc.found, cabs), [{game: "Roam", board: "Most days", name: "Bo", value: "40 days"}]);
    assert.ok(seen.every(([u, c]) => c === "omit" && !u.includes("soon") && !u.includes("..")), JSON.stringify(seen));
    assert.strictEqual(seen.length, 5);
    assert.deepStrictEqual(F.open(doc.found, cabs), ["Frog Hopper"]);
    const again = await F.load("https://api.example", deployed, s);
    assert.strictEqual(seen.length, 5, "kept for the session");
    assert.deepStrictEqual(again.games, doc.games);
  });

  await test("with the service down the board says so and likes are null", async () => {
    globalThis.fetch = async () => { throw new Error("down"); };
    const doc = await F.load("https://api.example", deployed, store());
    assert.strictEqual(doc.off, true);
    assert.strictEqual(await F.likes("https://api.example"), null);
    globalThis.fetch = fakeFetch({"/v1/likes/counts": {roam: 3, "Bad Slug": 2, apex: -1}}, []);
    assert.deepStrictEqual(await F.likes("https://api.example"), {roam: 3});
  });

  if (failures) { console.log(failures + " failed"); process.exit(1); }
})();

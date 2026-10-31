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
      if (body === undefined) return {ok: false, status: 404, json: async () => ({})};
      if (typeof body === "number") return {ok: body < 300, status: body, json: async () => ({})};
      return {ok: true, status: 200, json: async () => body};
    };
  }
  function store() { const m = new Map(); return {getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v))}; }
  const deployed = cabs.map((c) => Object.assign({deployed: true}, c)).concat([{slug: "soon", title: "Soon", deployed: false}]);

  await test("before /v1/boards/top exists (404), load asks each deployed game's boards, then each board's top", async () => {
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
    assert.strictEqual(seen[0][0], "https://api.example/v1/boards/top");
    assert.strictEqual(seen.length, 6);
    assert.deepStrictEqual(F.open(doc.found, cabs), ["Frog Hopper"]);
    const again = await F.load("https://api.example", deployed, s);
    assert.strictEqual(seen.length, 6, "kept for the session");
    assert.deepStrictEqual(again.games, doc.games);
  });

  const TOP = {verified: false, notice: "not verified", boards: [
    {slug: "tidewater", board: {id: "fewest-days", title: "Fewest days"}, top: {displayName: "Zed", value: 3, achievedAt: "2026-10-30T00:00:00Z"}},
    {slug: "roam", board: {id: "most-days", title: "Most days", unit: "days", integer: true, order: "desc"},
      top: {displayName: "Bo", value: 40, achievedAt: "2026-10-30T00:00:00Z"}},
    {slug: "roam", board: {id: "../x", title: "Bad"}, top: {displayName: "Evil", value: 1}},
    {slug: "rock-paper-scissors", board: {id: "best-streak", title: "Best streak", unit: "wins", integer: true}, top: null},
    {slug: "soon", board: {id: "b", title: "B"}, top: {displayName: "Early", value: 1}},
    {slug: "frog-hopper", board: {id: "fastest-crossing", title: "Fastest crossing", unit: "seconds"}, top: null},
    null, {slug: "frog-hopper"},
  ]};

  await test("load reads every board's #1 in one request, kept to the deployed cabinets", async () => {
    const seen = [], s = store();
    globalThis.fetch = fakeFetch({"/v1/boards/top": TOP}, seen);
    const doc = await F.load("https://api.example", deployed, s);
    assert.deepStrictEqual(seen, [["https://api.example/v1/boards/top", "omit"]]);
    assert.strictEqual(doc.off, false);
    // tidewater is not a cabinet here and "soon" is not deployed: neither is shown.
    assert.deepStrictEqual(doc.games, ["roam", "rock-paper-scissors", "frog-hopper"]);
    assert.deepStrictEqual(doc.found[0], {slug: "roam", board: {id: "most-days", title: "Most days", unit: "days", integer: true},
      top: {displayName: "Bo", value: 40}});
    assert.deepStrictEqual(F.champions(doc.found, cabs), [{game: "Roam", board: "Most days", name: "Bo", value: "40 days"}]);
    assert.deepStrictEqual(F.open(doc.found, cabs), ["Rock Paper Scissors", "Frog Hopper"]);
    await F.load("https://api.example", deployed, s);
    assert.strictEqual(seen.length, 1, "kept for the session");
  });

  await test("an unreadable 404 (no CORS headers) also falls back; a 5xx or 429 does not", async () => {
    const seen = [];
    globalThis.fetch = async (url, opts) => {
      seen.push(url);
      if (url.endsWith("/v1/boards/top")) throw new TypeError("Failed to fetch");
      return fakeFetch({"/v1/games/roam/boards": {boards: [{id: "most-days", title: "Most days"}]},
        "/v1/boards/roam/most-days?limit=1": {entries: [{displayName: "Bo", value: 40}]}}, [])(url, opts);
    };
    const doc = await F.load("https://api.example", deployed, store());
    assert.deepStrictEqual(F.champions(doc.found, cabs).map((r) => r.name), ["Bo"]);
    assert.ok(seen.length > 1);
    for (const code of [429, 500, 503]) {
      const asked = [];
      globalThis.fetch = fakeFetch({"/v1/boards/top": code}, asked);
      const off = await F.load("https://api.example", deployed, store());
      assert.strictEqual(off.off, true, String(code));
      assert.strictEqual(asked.length, 1, "no fallback storm on " + code);
    }
    // An answer without a boards list is a failure too, and is not kept.
    const s = store();
    globalThis.fetch = fakeFetch({"/v1/boards/top": {boards: "nope"}}, []);
    assert.strictEqual((await F.load("https://api.example", deployed, s)).off, true);
    assert.strictEqual(s.getItem("arcade-hall.fame"), null);
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

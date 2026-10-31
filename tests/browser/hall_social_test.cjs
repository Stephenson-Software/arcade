// Unit tests for src/arcade/hall_assets/hall-social.js (the card's likes,
// leaderboard and achievements text), under plain node:
//   node tests/browser/hall_social_test.cjs
const assert = require("assert");
const path = require("path");
const S = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-social.js"));

let failures = 0;
function test(name, fn) {
  try { fn(); console.log("ok", name); } catch (e) { failures++; console.log("FAIL", name, "\n ", e.stack); }
}

test("like counts keep well-formed slugs and counts only", () => {
  assert.deepStrictEqual(S.parseCounts({roam: 3, apex: 1.7, "Bad Slug": 2, x: 1, fishe: -1, kindling: "2"}), {roam: 3, apex: 1});
  assert.deepStrictEqual(S.parseCounts(null), {});
  assert.deepStrictEqual(S.parseCounts([1, 2]), {});
});

test("likes read as words, and nothing for none", () => {
  assert.strictEqual(S.likesText(0), "");
  assert.strictEqual(S.likesText(undefined), "");
  assert.strictEqual(S.likesText(1), "1 like");
  assert.strictEqual(S.likesText(1204), "1,204 likes");
});

test("a score carries its board's unit, singular for one", () => {
  const secs = {integer: false, unit: "seconds"}, days = {integer: true, unit: "days"};
  assert.strictEqual(S.valueText(secs, 12.43), "12.4 seconds");
  assert.strictEqual(S.valueText(secs, 1), "1 second");
  assert.strictEqual(S.valueText(days, 1), "1 day");
  assert.strictEqual(S.valueText(days, 1024), "1,024 days");
  assert.strictEqual(S.valueText({integer: true, unit: "wins"}, 7), "7 wins");
  assert.strictEqual(S.valueText({integer: true, unit: "boss"}, 1), "1 boss");
  assert.strictEqual(S.valueText({integer: true}, 5), "5");
  assert.strictEqual(S.valueText(days, NaN), "");
});

test("the leaders are the top three, malformed entries skipped", () => {
  const board = {integer: true, unit: "wins"};
  const entries = [
    {rank: 1, displayName: "Ada", value: 9},
    {rank: 2, displayName: "", value: 8},
    {rank: 2, displayName: "Bo", value: 8},
    {rank: 4, displayName: "Cy", value: 3},
    {rank: 5, displayName: "Di", value: 1},
  ];
  assert.deepStrictEqual(S.leaders(board, entries), [
    {rank: 1, name: "Ada", value: "9 wins"},
    {rank: 2, name: "Bo", value: "8 wins"},
    {rank: 4, name: "Cy", value: "3 wins"},
  ]);
  assert.deepStrictEqual(S.leaders(board, null), []);
});

test("achievements are counted, and nothing for none", () => {
  assert.strictEqual(S.achievementsText({achievements: []}), "");
  assert.strictEqual(S.achievementsText({achievements: [{id: "a"}]}), "1 achievement");
  assert.strictEqual(S.achievementsText({achievements: [{}, {}, {}]}), "3 achievements");
  assert.strictEqual(S.achievementsText(null), "");
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }

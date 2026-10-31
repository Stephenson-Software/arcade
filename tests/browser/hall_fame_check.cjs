// Checks the Hall of Fame board in a real browser against a mocked arcade-social:
// with GET /v1/boards/top it must make that one request and no per-game reads;
// with the route missing (a 404 sent without CORS headers, as an arcade-social
// from before the route answers) it must fall back to the per-game reads.
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_fame_check.cjs <hall url> <out dir>
//
// <hall url> is a hall served by tools/hall_dev_server.py. Runs a desktop
// window and an iPhone 13 in each mode, screenshots the board and writes
// <out dir>/fame.json. Exits non-zero when a check fails.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");

const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];
const API = "https://api.play.danielstephenson.dev";
const BOARDS = {
  roam: [{id: "most-days", title: "Most days in one world", unit: "days", integer: true, order: "desc"}],
  "frog-hopper": [{id: "fastest-crossing", title: "Fastest crossing", unit: "seconds", order: "asc"}],
  "rock-paper-scissors": [{id: "best-streak", title: "Best streak", unit: "wins", integer: true, order: "desc"}],
};
const TOPS = {"roam/most-days": ["Wren", 212], "frog-hopper/fastest-crossing": ["Marisol", 7.25]};
const FAME = {x: 4.2, z: 1.3, yaw: -Math.PI / 2};

async function run(b, hallUrl, out, name, ctxOpts, mode) {
  const ctx = await b.newContext(ctxOpts);
  // The page names arcade-social in <meta name="arcade-social"> and allows it in connect-src.
  await ctx.route((u) => new URL(u).pathname.match(/\/hall\/(index\.html)?$/), async (route) => {
    const res = await route.fetch();
    let body = await res.text();
    if (!body.includes('name="arcade-social"')) body = body.replace("</head>", `<meta name="arcade-social" content="${API}">\n</head>`);
    const headers = Object.assign({}, res.headers());
    for (const k of Object.keys(headers)) {
      if (k.toLowerCase() === "content-security-policy" && !headers[k].includes(API)) headers[k] = headers[k].replace("connect-src 'self'", `connect-src 'self' ${API}`);
    }
    await route.fulfill({response: res, body, headers});
  });
  const asked = [];
  await ctx.route(API + "/**", async (route) => {
    const p = new URL(route.request().url()).pathname;
    asked.push(p);
    const cors = {"access-control-allow-origin": "*"};
    let body = null, m;
    if (p === "/v1/boards/top") {
      // The old service has no such route: a bare 404 with no CORS headers.
      if (mode === "fallback") return route.fulfill({status: 404, contentType: "application/json", body: '{"error": "not found"}'});
      body = {verified: false, notice: "not verified", boards: []};
      for (const [slug, list] of Object.entries(BOARDS)) {
        for (const board of list) {
          const t = TOPS[slug + "/" + board.id];
          body.boards.push({slug, board, top: t ? {displayName: t[0], value: t[1], achievedAt: "2026-10-30T12:00:00Z"} : null});
        }
      }
    } else if ((m = p.match(/^\/v1\/games\/([a-z0-9-]+)\/boards$/))) body = {boards: BOARDS[m[1]] || []};
    else if ((m = p.match(/^\/v1\/boards\/([a-z0-9-]+)\/([a-z0-9-]+)$/))) {
      const t = TOPS[m[1] + "/" + m[2]];
      body = {entries: t ? [{displayName: t[0], value: t[1], rank: 1}] : []};
    } else if (p === "/v1/likes/counts") body = {roam: 12};
    else body = {};
    await route.fulfill({status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(body)});
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await page.goto(`${hallUrl}?at=tidewater`, {waitUntil: "commit"});
  await page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
  await page.waitForFunction(() => __hall.state.fame && __hall.state.fame.state !== "loading", null, {timeout: 60000});
  await page.evaluate((at) => __hall.place(at.x, at.z, at.yaw, 0.02), FAME);
  await page.waitForTimeout(2500);
  await page.screenshot({path: path.join(out, `${name}-${mode}.png`)});
  const fame = await page.evaluate(() => __hall.state.fame);
  // The cabinet card (hall-social.js) reads the nearby game's boards and
  // achievements on its own; the board never reads achievements, so a game
  // whose achievements were read is the card's and is left out of the count.
  const card = new Set(asked.map((p) => (p.match(/^\/v1\/games\/([a-z0-9-]+)\/achievements$/) || [])[1]).filter(Boolean));
  const slugOf = (p) => (p.match(/^\/v1\/(?:games|boards)\/([a-z0-9-]+)\//) || [])[1];
  const boardReads = asked.filter((p) => (p.startsWith("/v1/boards/") || p.startsWith("/v1/games/")) && !p.endsWith("/achievements")
    && !card.has(slugOf(p)));
  await ctx.close();
  const r = {profile: name, mode, fame, cardGames: [...card], boardReads: boardReads.length, top: boardReads.filter((p) => p === "/v1/boards/top").length,
    perGame: boardReads.filter((p) => p !== "/v1/boards/top").length, errors};
  const want = Object.keys(TOPS).length;
  r.ok = fame.state === "ready" && fame.rows === want && errors.length === 0
    && (mode === "top" ? r.top === 1 && r.perGame === 0 : r.top === 1 && r.perGame > 0);
  return r;
}

(async () => {
  const [hallUrl, out] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const b = await chromium.launch({args: GL});
  const results = [];
  for (const [name, opts] of [["desktop", {viewport: {width: 1024, height: 640}}], ["iphone13", devices["iPhone 13"]]]) {
    for (const mode of ["top", "fallback"]) results.push(await run(b, hallUrl, out, name, opts, mode));
  }
  await b.close();
  for (const r of results) console.log(JSON.stringify(r));
  fs.writeFileSync(path.join(out, "fame.json"), JSON.stringify(results, null, 1));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();

// Walk replays in a real browser (desktop and iPhone 13): the opt-in, the
// upload when a game opens, and "The hall today".
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_replays_check.cjs <hall url> <out dir>
//
// <hall url> is a hall served by tools/hall_dev_server.py (--embed on) with at
// least walks.K walks left today. When hall-people.js is not in the page yet,
// a stand-in HallPeople (this harness only) records what it is given and draws
// each figure as a grey capsule on an overlay, so the screenshots show them.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");

const STAND_IN = () => {
  window.addEventListener("DOMContentLoaded", () => {
    if (window.HallPeople) return;
    const cv = document.createElement("canvas");
    cv.id = "standin-people";
    cv.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:2";
    document.body.appendChild(cv);
    const layers = {};
    window.HallPeople = {standIn: true, layers, set(layer, people) { layers[layer] = people; }};
    (function draw() {
      requestAnimationFrame(draw);
      const h = window.__hall, C = window.HallControls;
      if (!h || !h.me || !h.kit) return;
      cv.width = innerWidth; cv.height = innerHeight;
      const g = cv.getContext("2d"), cam = h.kit.cam;
      const view = {x: h.me.x, y: 1.62, z: h.me.z, yaw: cam.yaw, pitch: cam.pitch, aspect: innerWidth / innerHeight, fov: h.settings.fov};
      for (const p of layers.replays || []) {
        const a = C.project(view, [p.x, 0.05, p.z], 5), b = C.project(view, [p.x, 1.7, p.z], 5);
        if (!a.on || !b.on) continue;
        const ax = (a.nx + 1) / 2 * innerWidth, ay = (1 - a.ny) / 2 * innerHeight, by = (1 - b.ny) / 2 * innerHeight;
        const w = Math.max(3, (ay - by) * 0.28);
        g.globalAlpha = p.alpha; g.fillStyle = `rgb(${p.color.map((c) => Math.round(c * 255)).join(",")})`;
        g.beginPath(); g.roundRect(ax - w / 2, by + w * 0.9, w, ay - by - w * 0.9, w / 2); g.fill();
        g.beginPath(); g.arc(ax, by + w * 0.45, w * 0.42, 0, 2 * Math.PI); g.fill();
      }
    })();
  });
};

async function run(name, contextOptions, hallUrl, out) {
  const b = await chromium.launch({args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  // Each run its own client address (as Traefik would send), so the rate limit (one walk per client
  // per 10 minutes) does not refuse the second device's walk.
  const ctx = await b.newContext(Object.assign({extraHTTPHeaders: {"X-Forwarded-For": "198.51.100." + (Date.now() % 250)}}, contextOptions));
  await ctx.addInitScript(STAND_IN);
  // With the real hall-people.js, keep what each layer was last given, as the stand-in does.
  await ctx.addInitScript(() => window.addEventListener("DOMContentLoaded", () => {
    const P = window.HallPeople;
    if (!P || P.standIn || P.layers) return;
    const set = P.set.bind(P);
    P.layers = {};
    P.set = (layer, people) => { P.layers[layer] = people.map((p) => Object.assign({}, p)); return set(layer, people); };
  }));
  const r = {device: name};
  const posts = [];
  ctx.on("request", (q) => { if (q.method() === "POST" && q.url().includes("/api/walks")) posts.push(q.postData()); });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const ready = () => page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2 && window.__hallReplays && __hallReplays.fetched, null, {timeout: 120000});
  const tap = (sel) => (contextOptions.hasTouch ? page.tap(sel) : page.click(sel));
  await page.goto(hallUrl + "?quality=0", {waitUntil: "commit"});
  await ready();

  // 1. Off by default: nothing is recorded or sent.
  r.defaultOff = await page.evaluate(() => !__hallReplays.sharing && !document.getElementById("set-walk").checked);
  if (await page.locator("#help").isHidden()) await tap("#help-btn");
  await tap("#settings-btn");
  await page.locator("#set-walk").scrollIntoViewIfNeeded();
  const opt = await page.locator("label.opt:has(#set-walk)").boundingBox();
  r.toggleHeight = Math.round(opt.height);
  r.todayButtonShown = await page.locator("#today-btn").isVisible();
  const todayBox = await page.locator("#today-btn").boundingBox();
  r.todayButtonHeight = todayBox && Math.round(todayBox.height);
  await page.screenshot({path: path.join(out, `${name}-settings.png`)});
  const slug = await page.evaluate(() => __hall.layout.cabinets[2].slug);
  await page.evaluate((s) => __hall.walkTo(s), slug);
  await page.waitForTimeout(3000);
  r.offRecorded = await page.evaluate(() => __hallReplays.recorded);
  await page.evaluate(() => __hallReplays.upload());
  r.offPosts = posts.length;

  // 2. On: the walk is recorded, and sent once when a game opens.
  await tap("label.opt:has(#set-walk)");
  r.stored = await page.evaluate(() => localStorage.getItem("arcade-hall.shareWalk"));
  // One in sight of the door, so walking to it goes straight there (walkTo does not path-find).
  const second = await page.evaluate(() => __hall.layout.cabinets.map((c) => [HallWalk.front(c).z, c.slug])
    .sort((a, b) => b[0] - a[0]).map((x) => x[1]).find((s) => s !== __hall.near));
  await page.evaluate((s) => __hall.walkTo(s), second);
  await page.waitForFunction((s) => __hall.near === s, second, {timeout: 30000});
  await page.waitForTimeout(800);
  r.recorded = await page.evaluate(() => __hallReplays.recorded);
  const response = page.waitForResponse((q) => q.url().endsWith("/api/walks") && q.request().method() === "POST", {timeout: 15000});
  await page.evaluate((s) => __hall.play(s), second);
  const res = await response;
  r.uploadStatus = res.status();
  // What was sent (a beacon's body is not visible to Playwright's request).
  const body = await page.evaluate(() => __hallReplays.sent);
  r.upload = {keys: Object.keys(body).sort(), points: body.points.length, visits: body.visits.map((v) => v.slug),
    onGrid: body.points.every(([x, z]) => Number.isInteger(x * 4) && Number.isInteger(z * 4))};
  await page.waitForTimeout(500);
  r.postsAfterGame = posts.length;
  await page.evaluate(() => __hall.back());
  await page.waitForTimeout(1500);
  await page.evaluate(() => __hallReplays.upload());
  r.postsTotal = posts.length;  // still one: once per visit

  // 3. The hall today (?replay=today), through HallPeople.
  await page.goto(hallUrl + "?quality=0&replay=today", {waitUntil: "commit"});
  await ready();
  await page.waitForFunction(() => __hallReplays.playing, null, {timeout: 20000});
  await page.waitForTimeout(4000);
  r.replay = await page.evaluate(() => {
    const W = window.HallWalk, world = W.world(__hall.layout), people = window.HallPeople.layers.replays || [];
    return {standIn: !!window.HallPeople.standIn, walks: __hallReplays.walks, figures: people.length,
      clear: people.every((p) => W.clear(p.x, p.z, world, 0.05)),
      fields: people.length ? Object.keys(people[0]).sort() : [], pressed: document.getElementById("today-btn").getAttribute("aria-pressed")};
  });
  // Face down the hall, from mid-floor, for the picture.
  await page.evaluate(() => { const s = __hall.layout.room.spawn; __hall.place(0, (s ? s.z : 4) - 2, Math.PI / 2, 0.12); });
  await page.waitForTimeout(2500);
  await page.screenshot({path: path.join(out, `${name}-today.png`)});
  const a = await page.evaluate(() => JSON.stringify(window.HallPeople.layers.replays));
  await page.waitForTimeout(1000);
  r.moving = a !== (await page.evaluate(() => JSON.stringify(window.HallPeople.layers.replays)));
  // Reduced motion: they stand still.
  if (await page.locator("#help").isHidden()) await tap("#help-btn");
  if (await page.locator("#settings").isHidden()) await tap("#settings-btn");
  await page.locator("#set-reduce").scrollIntoViewIfNeeded();
  await tap("label.opt:has(#set-reduce)");
  await page.waitForTimeout(400);
  const c = await page.evaluate(() => JSON.stringify(window.HallPeople.layers.replays));
  await page.waitForTimeout(1200);
  r.stillUnderReducedMotion = c === (await page.evaluate(() => JSON.stringify(window.HallPeople.layers.replays)));
  await page.locator("#today-btn").scrollIntoViewIfNeeded();
  await page.screenshot({path: path.join(out, `${name}-today-panel.png`)});
  await tap("#today-btn");
  r.afterStop = await page.evaluate(() => ({playing: __hallReplays.playing, figures: (window.HallPeople.layers.replays || []).length}));
  r.errors = errors;
  await b.close();
  return r;
}

(async () => {
  const [hallUrl, out] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const results = [];
  results.push(await run("desktop", {viewport: {width: 1280, height: 800}}, hallUrl, out));
  results.push(await run("iphone13", Object.assign({}, devices["iPhone 13"]), hallUrl, out));
  fs.writeFileSync(path.join(out, "replays.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch((e) => { console.error(e); process.exit(1); });

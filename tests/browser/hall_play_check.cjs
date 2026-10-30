// Plays every cabinet in the hall and reports how each one opened.
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_play_check.cjs <hall url> <out dir> [slug ...]
//
// <hall url> is a hall served by tools/hall_dev_server.py (--embed on). The
// games are the live ones. Their gateway headers currently let only
// danielstephenson.dev frame them, so this script widens frame-ancestors to
// the hall's origin on the way in, as the gateway change that goes with
// ARCADE_HALL_EMBED=on does, and leaves every other header as served.
// For each game: open it from in front of its cabinet, wait for the frame,
// read crossOriginIsolated inside it, screenshot, press "Back to the hall"
// and check the visitor is where they were. Writes <out dir>/play.json.
const {chromium} = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const [hallUrl, out, ...only] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const origin = new URL(hallUrl).origin;
  const b = await chromium.launch({args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  const ctx = await b.newContext({viewport: {width: 1024, height: 640}});
  await ctx.route(/^https:\/\/[a-z0-9-]+\.play\.danielstephenson\.dev\//, async (route) => {
    const res = await route.fetch();
    const headers = Object.assign({}, res.headers());
    for (const k of Object.keys(headers)) {
      if (k.toLowerCase() === "content-security-policy") {
        headers[k] = headers[k].replace(/frame-ancestors ([^;]*)/, `frame-ancestors $1 ${origin}`);
      }
    }
    await route.fulfill({response: res, headers});
  });
  const page = await ctx.newPage();
  const ready = () => page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
  await page.goto(hallUrl + "?quality=0", {waitUntil: "commit"});
  await ready();
  const slugs = only.length ? only : await page.evaluate(() => __hall.layout.cabinets.filter((c) => c.deployed).map((c) => c.slug));
  const results = [];
  for (const slug of slugs) {
    const r = {slug};
    try {
      await page.goto(`${hallUrl}?quality=0&at=${slug}`, {waitUntil: "commit"});
      await ready();
      r.how = await page.evaluate((s) => __hall.howFor(s), slug);
      const before = await page.evaluate(() => __hall.me);
      const errors = [];
      const onErr = (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); };
      page.on("console", onErr);
      await page.evaluate((s) => __hall.play(s), slug);
      if (r.how === "switch") await page.waitForURL(/play=/, {timeout: 30000});
      await page.waitForFunction((s) => window.__hall && __hall.playing === s, slug, {timeout: 120000});
      const frame = await (await page.$("#player-frame")).contentFrame();
      await frame.waitForLoadState("load", {timeout: 60000}).catch(() => {});
      await page.waitForTimeout(slug === "roam" ? 45000 : 12000);
      r.hallIsolated = await page.evaluate(() => self.crossOriginIsolated);
      r.frame = await frame.evaluate(() => ({url: location.href, isolated: self.crossOriginIsolated,
        sab: typeof SharedArrayBuffer !== "undefined", title: document.title,
        text: (document.body && document.body.innerText || "").slice(0, 160),
        canvases: document.querySelectorAll("canvas").length})).catch((e) => ({error: String(e).slice(0, 200)}));
      await page.screenshot({path: path.join(out, `${slug}.png`), timeout: 120000});
      await page.click("#back", {force: true, timeout: 60000});
      await page.waitForFunction(() => __hall.playing === null, null, {timeout: 10000});
      const after = await page.evaluate(() => __hall.me);
      r.sameSpot = Math.hypot(after.x - before.x, after.z - before.z) < 0.05;
      r.consoleErrors = errors.slice(0, 5);
      page.off("console", onErr);
    } catch (e) {
      r.error = String(e.message || e).split("\n")[0];
    }
    console.log(JSON.stringify(r));
    results.push(r);
  }
  fs.writeFileSync(path.join(out, "play.json"), JSON.stringify(results, null, 1));
  await b.close();
})();

// Checks the hall's atmosphere in a real browser: live trailer screens,
// the cabinets' spatial sound, warm marquees and the Hall of Fame board.
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_atmosphere_check.cjs <hall url> <out dir>
//
// <hall url> is a hall served by tools/hall_dev_server.py. For each profile
// (a desktop window, an iPhone 13, the desktop in economy, the desktop with
// reduce motion) it stands in front of a cabinet with a trailer, waits, and
// records which screens play and whether their frames reached the texture,
// the frame rate while they play (with the sound on), and a screenshot.
// Writes <out dir>/atmosphere.json.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");

const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"];

async function run(b, hallUrl, out, name, ctxOpts, query, opts = {}) {
  const ctx = await b.newContext(ctxOpts);
  if (opts.reduce) await ctx.addInitScript(() => localStorage.setItem("arcade-hall.settings", JSON.stringify({reduceMotion: true})));
  // Every sound the page makes passes an analyser on its way out, to measure how loud it is.
  await ctx.addInitScript(() => {
    const connect = AudioNode.prototype.connect;
    AudioNode.prototype.connect = function (dest, ...rest) {
      if (dest instanceof AudioDestinationNode) {
        const c = dest.context;
        if (!c.__meter) { c.__meter = c.createAnalyser(); c.__meter.fftSize = 2048; connect.call(c.__meter, dest); window.__meterCtx = c; }
        return connect.call(this, c.__meter, ...rest);
      }
      return connect.call(this, dest, ...rest);
    };
    window.__rms = async (ms) => {
      const c = window.__meterCtx;
      if (!c) return null;
      const a = c.__meter, buf = new Float32Array(a.fftSize);
      let sum = 0, n = 0, peak = 0;
      const end = performance.now() + ms;
      while (performance.now() < end) {
        a.getFloatTimeDomainData(buf);
        for (const v of buf) { sum += v * v; peak = Math.max(peak, Math.abs(v)); }
        n += buf.length;
        await new Promise((r) => setTimeout(r, 40));
      }
      return {rms: +Math.sqrt(sum / n).toFixed(4), peak: +peak.toFixed(3)};
    };
  });
  // arcade-social: the page names it in <meta name="arcade-social"> and allows it
  // in connect-src (arcade PR #59, feat/hall-social); added here when the hall
  // under test predates that. opts.fake answers its boards with made-up scores.
  const API = "https://api.play.danielstephenson.dev";
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
  if (opts.fake) {
    await ctx.route(API + "/v1/**", async (route) => {
      const p = new URL(route.request().url()).pathname;
      const decl = {
        roam: [{id: "most-days", title: "Most days in one world", unit: "days", integer: true}, {id: "most-rooms", title: "Most rooms explored", unit: "rooms", integer: true}],
        "frog-hopper": [{id: "fastest-crossing", title: "Fastest crossing", unit: "seconds"}],
        "rock-paper-scissors": [{id: "best-streak", title: "Best streak", unit: "wins", integer: true}],
      };
      const top = {"roam/most-days": ["Wren", 212], "roam/most-rooms": ["Otto", 1840], "frog-hopper/fastest-crossing": ["Marisol", 7.25], "rock-paper-scissors/best-streak": ["Scout", 14]};
      let body = null, m;
      if ((m = p.match(/^\/v1\/games\/([a-z0-9-]+)\/boards$/))) body = {boards: decl[m[1]] || []};
      else if ((m = p.match(/^\/v1\/boards\/([a-z0-9-]+)\/([a-z0-9-]+)$/))) { const t = top[m[1] + "/" + m[2]]; body = {entries: t ? [{displayName: t[0], value: t[1], rank: 1}] : []}; }
      else if (p === "/v1/likes/counts") body = {roam: 12, tidewater: 9, apex: 2};
      if (!body) return route.continue();
      await route.fulfill({status: 200, contentType: "application/json", headers: {"access-control-allow-origin": "*"}, body: JSON.stringify(body)});
    });
  }
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await page.goto(`${hallUrl}?at=${opts.at || "tidewater"}${query}`, {waitUntil: "commit"});
  await page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
  if (opts.sound) await page.evaluate(() => document.getElementById("sound").click());
  await page.waitForTimeout(opts.wait || 6000);
  const f0 = await page.evaluate(() => __hall.state.frames);
  const t0 = Date.now();
  await page.waitForTimeout(5000);
  const r = await page.evaluate(() => ({
    trailers: __hall.trailers, near: __hall.near, economy: __hall.state.economy,
    sound: __hall.sound, voices: __hall.state.voices || null,
    warm: __hall.state.warm || null, fame: __hall.state.fame || null, trailerMs: __hall.state.trailerMs || 0,
  }));
  r.fps = +((await page.evaluate(() => __hall.state.frames) - f0) / ((Date.now() - t0) / 1000)).toFixed(1);
  r.profile = name;
  await page.screenshot({path: path.join(out, `${name}.png`)});
  if (opts.sound) {
    r.loud = await page.evaluate(() => window.__rms(6000));
    // From the middle of the far walkway, by the wall: the cabinets fade, the hum stays.
    await page.evaluate(() => __hall.place(-9.2, -17.5, Math.PI / 2, 0.05));
    await page.waitForTimeout(1500);
    r.loudFar = await page.evaluate(() => window.__rms(6000));
    r.voicesFar = await page.evaluate(() => __hall.state.voices);
    await page.evaluate((s) => __hall.walkTo(s), opts.at || "tidewater");
  }
  if (opts.fame) {
    // From inside the door, down the hall: the warm marquees of the most played.
    await page.evaluate(() => __hall.place(-1.0, 3.2, Math.PI / 2 - 0.25, -0.05));
    await page.waitForTimeout(2500);
    await page.screenshot({path: path.join(out, `${name}-door.png`)});
    // Turn round to face the door: the Hall of Fame board beside it.
    await page.evaluate((at) => __hall.place(at.x, at.z, at.yaw, 0.02), opts.fame);
    await page.waitForTimeout(3000);
    await page.screenshot({path: path.join(out, `${name}-fame.png`)});
  }
  r.errors = errors.slice(0, 5);
  await ctx.close();
  return r;
}

(async () => {
  const [hallUrl, out, only] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const b = await chromium.launch({args: GL});
  const results = [];
  const desk = {viewport: {width: 1024, height: 640}};
  const fame = {x: 4.2, z: 1.3, yaw: -Math.PI / 2};
  results.push(await run(b, hallUrl, out, "desktop", desk, "", {sound: true, fame}));
  results.push(await run(b, hallUrl, out, "desktop-fake-scores", desk, "", {fame, fake: true, wait: 4000}));
  if (only === "desktop") { console.log(JSON.stringify(results[0])); await b.close(); return; }
  results.push(await run(b, hallUrl, out, "iphone13", devices["iPhone 13"], "", {sound: true, fame}));
  results.push(await run(b, hallUrl, out, "economy", desk, "&economy=1", {sound: true}));
  results.push(await run(b, hallUrl, out, "reduce-motion", desk, "", {reduce: true}));
  results.push(await run(b, hallUrl, out, "desktop-no-trailers", desk, "&trailers=0", {sound: true}));
  for (const r of results) console.log(JSON.stringify(r));
  fs.writeFileSync(path.join(out, "atmosphere.json"), JSON.stringify(results, null, 1));
  await b.close();
})();

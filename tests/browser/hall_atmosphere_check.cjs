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
  r.errors = errors.slice(0, 5);
  await page.screenshot({path: path.join(out, `${name}.png`)});
  if (opts.fame) {
    // Turn round to face the door: the Hall of Fame board beside it.
    await page.evaluate((at) => __hall.place(at.x, at.z, at.yaw, 0.02), opts.fame);
    await page.waitForTimeout(3000);
    await page.screenshot({path: path.join(out, `${name}-fame.png`)});
  }
  await ctx.close();
  return r;
}

(async () => {
  const [hallUrl, out] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const b = await chromium.launch({args: GL});
  const results = [];
  const desk = {viewport: {width: 1024, height: 640}};
  const fame = {x: 3.6, z: 1.2, yaw: -Math.PI / 2};
  results.push(await run(b, hallUrl, out, "desktop", desk, "", {sound: true, fame}));
  results.push(await run(b, hallUrl, out, "iphone13", devices["iPhone 13"], "", {sound: true, fame}));
  results.push(await run(b, hallUrl, out, "economy", desk, "&economy=1", {sound: true}));
  results.push(await run(b, hallUrl, out, "reduce-motion", desk, "", {reduce: true}));
  results.push(await run(b, hallUrl, out, "desktop-no-trailers", desk, "&trailers=0", {sound: true}));
  for (const r of results) console.log(JSON.stringify(r));
  fs.writeFileSync(path.join(out, "atmosphere.json"), JSON.stringify(results, null, 1));
  await b.close();
})();

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
  if (opts.sound) {
    r.loud = await page.evaluate(() => window.__rms(6000));
    // From the middle of the far walkway, by the wall: the cabinets fade, the hum stays.
    await page.evaluate(() => __hall.place(-9.2, -17.5, Math.PI / 2, 0.05));
    await page.waitForTimeout(1500);
    r.loudFar = await page.evaluate(() => window.__rms(6000));
    r.voicesFar = await page.evaluate(() => __hall.state.voices);
    await page.evaluate((s) => __hall.walkTo(s), opts.at || "tidewater");
  }
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
  const [hallUrl, out, only] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const b = await chromium.launch({args: GL});
  const results = [];
  const desk = {viewport: {width: 1024, height: 640}};
  const fame = {x: 3.6, z: 1.2, yaw: -Math.PI / 2};
  results.push(await run(b, hallUrl, out, "desktop", desk, "", {sound: true, fame}));
  if (only === "desktop") { console.log(JSON.stringify(results[0])); await b.close(); return; }
  results.push(await run(b, hallUrl, out, "iphone13", devices["iPhone 13"], "", {sound: true, fame}));
  results.push(await run(b, hallUrl, out, "economy", desk, "&economy=1", {sound: true}));
  results.push(await run(b, hallUrl, out, "reduce-motion", desk, "", {reduce: true}));
  results.push(await run(b, hallUrl, out, "desktop-no-trailers", desk, "&trailers=0", {sound: true}));
  for (const r of results) console.log(JSON.stringify(r));
  fs.writeFileSync(path.join(out, "atmosphere.json"), JSON.stringify(results, null, 1));
  await b.close();
})();

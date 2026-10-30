// Captures the hall's README/PR media and its frame times.
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_media.cjs <hall url> <out dir>
//
// <hall url>: tools/hall_dev_server.py --embed on. Writes, in <out dir>:
//   hall-walk-desktop.png      1280x720, looking down the aisle
//   hall-walk-iphone.png       iPhone 13: the stick and "Tap to play" at a cabinet (after a real tap-to-walk)
//   hall-walk-iphone-play.png  iPhone 13: the game in its frame, "Back to the hall" above it
//   frames/NNN.png             a walk up to a cabinet, E, the game, and back (drive mode; make a GIF of them)
//   perf.json                  ms/frame per quality tier, desktop and iPhone
// The live games refuse to be framed by anything but danielstephenson.dev
// until the gateway allows play.<base>; frame-ancestors is widened on the way
// in, as in hall_play_check.cjs.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");

const GAME = process.env.HALL_GAME || "env-lib-cpp";

(async () => {
  const [hallUrl, out] = process.argv.slice(2);
  fs.mkdirSync(path.join(out, "frames"), {recursive: true});
  const origin = new URL(hallUrl).origin;
  const gl = process.env.HALL_GL === "llvmpipe" ? ["--use-gl=angle", "--use-angle=gl", "--ignore-gpu-blocklist"]
    : ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];
  const b = await chromium.launch({args: gl, headless: process.env.HALL_GL !== "llvmpipe"});
  async function widen(ctx) {
    await ctx.route(/^https:\/\/[a-z0-9-]+\.play\.danielstephenson\.dev\//, async (route) => {
      const res = await route.fetch();
      const headers = Object.assign({}, res.headers());
      for (const k of Object.keys(headers)) if (k.toLowerCase() === "content-security-policy")
        headers[k] = headers[k].replace(/frame-ancestors ([^;]*)/, `frame-ancestors $1 ${origin}`);
      await route.fulfill({response: res, headers});
    });
  }
  const perf = {gl: process.env.HALL_GL || "swiftshader"};
  const settle = (p) => p.waitForFunction(() => window.__hall && __hall.state.frames > 2 && __hall.state.posters >= 29,
    null, {timeout: 240000});
  const hideHelp = (p) => p.evaluate(() => { document.getElementById("help").hidden = true; });

  async function measure(p, q, label) {
    await p.goto(`${hallUrl}?quality=${q}&fps=1`, {waitUntil: "commit"});
    await settle(p);
    await p.waitForTimeout(3000);
    await p.keyboard.down("w");
    const t0 = await p.evaluate(() => [performance.now(), __hall.kit.stats().frames]);
    await p.waitForTimeout(6000);
    const t1 = await p.evaluate(() => [performance.now(), __hall.kit.stats().frames, __hall.kit.stats()]);
    await p.keyboard.up("w");
    perf[label] = {quality: q, msPerFrame: +((t1[0] - t0[0]) / Math.max(1, t1[1] - t0[1])).toFixed(1),
      size: [t1[2].width, t1[2].height], lights: t1[2].lights, meshes: t1[2].meshes, primitives: t1[2].primitives};
    console.log(label, JSON.stringify(perf[label]));
  }

  // ---- desktop
  const desk = await b.newContext({viewport: {width: 1280, height: 720}});
  await widen(desk);
  const p = await desk.newPage();
  for (const q of [2, 1, 0]) await measure(p, q, `desktop-1280x720-q${q}`);

  await p.goto(`${hallUrl}?drive=1&quality=2`, {waitUntil: "commit"});
  await p.waitForFunction(() => window.__hall && __hall.kit, null, {timeout: 120000});
  await p.waitForFunction(() => __hall.state.posters >= 29, null, {timeout: 240000});
  await hideHelp(p);
  await p.evaluate(() => { __hall.place(0.35, 4.4, Math.PI / 2 + 0.03, 0.1); __hall.kit.drive(1); });
  await p.screenshot({path: path.join(out, "hall-walk-desktop.png")});

  // The walk: from the door to GAME's cabinet, E, the game, back.
  let n = 0, t = 2;
  const shot = async () => p.screenshot({path: path.join(out, "frames", String(n++).padStart(3, "0") + ".png"),
    clip: {x: 0, y: 0, width: 1280, height: 720}});
  await p.evaluate(() => { __hall.place(0, 5.2, Math.PI / 2, 0.06); __hall.kit.drive(2); });
  for (let i = 0; i < 6; i++) await shot();
  await p.evaluate((g) => __hall.walkTo(g), GAME);
  for (let i = 0; i < 90; i++) {
    t += 1 / 15;
    await p.evaluate((tt) => __hall.kit.drive(tt), t);
    if (i % 2 === 0) await shot();
    if (await p.evaluate((g) => __hall.near === g && !__hall.state.walking, GAME) && i > 40) break;
  }
  for (let i = 0; i < 8; i++) { t += 1 / 15; await p.evaluate((tt) => __hall.kit.drive(tt), t); }
  for (let i = 0; i < 8; i++) await shot();
  await p.keyboard.press("e");
  await p.waitForFunction((g) => __hall.playing === g, GAME, {timeout: 30000});
  await p.waitForTimeout(15000);
  for (let i = 0; i < 14; i++) { await shot(); await p.waitForTimeout(400); }
  await p.click("#back", {force: true});
  await p.evaluate((tt) => __hall.kit.drive(tt), t + 0.1);
  for (let i = 0; i < 8; i++) await shot();
  await desk.close();

  // ---- iPhone 13: a real tap to walk, then a real tap to play
  const phone = await b.newContext(Object.assign({}, devices["iPhone 13"]));
  await widen(phone);
  const m = await phone.newPage();
  for (const q of [1, 0]) await measure(m, q, `iphone13-q${q}`);
  await m.goto(`${hallUrl}?quality=1`, {waitUntil: "commit"});
  await settle(m);
  await hideHelp(m);
  const at = await m.evaluate((g) => {
    const c = __hall.layout.cabinets.find((k) => k.slug === g);
    const q = __hall.kit.project(...c.fr.p(0, 1.4, 0.3));
    return q && {x: q.x, y: q.y};
  }, GAME);
  await m.touchscreen.tap(at.x, at.y);
  await m.waitForFunction((g) => __hall.near === g, GAME, {timeout: 120000});
  await m.waitForTimeout(2500);
  await m.screenshot({path: path.join(out, "hall-walk-iphone.png")});
  perf.iphoneTapToWalk = await m.evaluate(() => ({near: __hall.near, prompt: document.getElementById("prompt").textContent}));
  await m.tap("#prompt");
  await m.waitForFunction((g) => __hall.playing === g, GAME, {timeout: 30000});
  await m.waitForTimeout(15000);
  await m.screenshot({path: path.join(out, "hall-walk-iphone-play.png")});
  await m.tap("#back");
  perf.iphoneBack = await m.evaluate(() => ({playing: __hall.playing, near: __hall.near}));
  fs.writeFileSync(path.join(out, "perf.json"), JSON.stringify(perf, null, 1));
  await b.close();
})();

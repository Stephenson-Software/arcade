// Checks people in the hall in a real browser, against a mocked arcade-social.
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_people_check.cjs <hall url> <out dir>
//
// <hall url> is a hall served by tools/hall_dev_server.py. arcade-social
// (https://api.play.danielstephenson.dev) is answered by route mocks: three
// people walking in front of the visitor and one standing at a cabinet, all
// with display names. Desktop and iPhone 13:
//   1. signed out: the figures are drawn, their names show, "Show me in the
//      hall" is off and disabled, with a sign-in link back to the same spot;
//   2. signed in: ticking it opts in (POST /v1/presence/optin), then the hall
//      sends its pose about once a second with the layout key, and its own
//      entry in the list is not drawn;
//   3. "See other people" off: polling stops and the figures go.
// Writes screenshots and <out dir>/people.json; exits 1 on a failed check.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-walk.js"));

const API = "https://api.play.danielstephenson.dev";
const NAMES = ["Ada", "Bo", "Cyrus", "Dee"];

(async () => {
  const [hallUrl, out] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive: true});
  const origin = new URL(hallUrl).origin;
  const b = await chromium.launch({args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  const report = {};
  let failed = 0;
  const check = (where, name, ok, detail) => {
    report[where] = report[where] || {};
    report[where][name] = {ok: !!ok, detail};
    if (!ok) failed++;
    console.log(ok ? "ok" : "FAIL", where, name, detail === undefined ? "" : JSON.stringify(detail));
  };

  for (const [label, opts] of [["desktop", {viewport: {width: 1280, height: 720}}], ["iphone13", devices["iPhone 13"]]]) {
    const ctx = await b.newContext(Object.assign({}, opts));
    const sim = {signedIn: false, optedIn: false, gets: 0, posts: [], optins: [], origin: null, layout: null, me: null};
    const cors = {"access-control-allow-origin": origin, "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type, x-play-client, accept", "access-control-allow-methods": "GET, POST, DELETE",
      "content-type": "application/json"};
    const json = (route, body, status = 200) => route.fulfill({status, headers: cors, body: JSON.stringify(body)});
    await ctx.route(API + "/**", async (route) => {
      const req = route.request(), url = new URL(req.url()), m = req.method();
      if (m === "OPTIONS") return route.fulfill({status: 204, headers: cors});
      if (url.pathname === "/v1/session") return json(route, {signedIn: sim.signedIn, signInUrl: API + "/signin"});
      if (url.pathname === "/v1/presence/me") return json(route, {optedIn: sim.optedIn});
      if (url.pathname === "/v1/presence/optin") { sim.optedIn = m === "POST"; sim.optins.push(m); return json(route, {optedIn: sim.optedIn}); }
      if (url.pathname === "/v1/presence" && m === "POST") {
        sim.posts.push({at: Date.now(), body: JSON.parse(req.postData() || "{}")});
        return json(route, {ok: sim.optedIn, ttl: 10});
      }
      if (url.pathname === "/v1/presence") {
        sim.gets++;
        sim.lastKey = url.searchParams.get("layout");
        return json(route, {people: people(sim), ttl: 10});
      }
      return json(route, {}, 404);
    });

    // Three people walking to and fro in front of where the visitor started, one at a cabinet.
    function people(s) {
      if (!s.layout || !s.me) return [];
      const t = Date.now() / 1000, me = s.me, fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw), rx = -fz, rz = fx;
      const world = W.world(s.layout), list = [];
      [[3.2, -0.7], [5, 0.8], [7.5, 0]].forEach(([d, side], i) => {
        const sway = Math.sin(t * 0.6 + i * 2) * 0.8;
        const p = W.resolve(me.x + fx * d + rx * (side + sway), me.z + fz * d + rz * (side + sway), world);
        list.push({id: "sess-" + i, name: NAMES[i], x: p.x, z: p.z, yaw: me.yaw + Math.PI, cabinet: null});
      });
      list.push({id: "sess-3", name: NAMES[3], x: 0, z: 0, yaw: 0, cabinet: s.atSlug});
      // The visitor's own entry, once they appear: it must not be drawn.
      const mine = s.posts.length ? s.posts[s.posts.length - 1].body : null;
      if (mine && s.optedIn) list.push({id: "sess-me", name: "Me", x: mine.x, z: mine.z, yaw: mine.yaw, cabinet: mine.cabinet});
      return list;
    }

    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error" && !/^Failed to load resource/.test(m.text())) errors.push(m.text()); });
    await page.goto(hallUrl + "?quality=0", {waitUntil: "commit"});
    await page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
    const info = await page.evaluate(() => ({layout: __hall.layout, me: __hall.me}));
    sim.layout = info.layout; sim.me = info.me;
    // The person at a cabinet: the one nearest in front of the visitor.
    const ahead = info.layout.cabinets.map((c) => ({c, d: Math.hypot(c.x - info.me.x, c.z - info.me.z),
      dot: (c.x - info.me.x) * -Math.cos(info.me.yaw) + (c.z - info.me.z) * -Math.sin(info.me.yaw)}))
      .filter((k) => k.dot > 2).sort((p, q) => p.d - q.d);
    sim.atSlug = ahead.length ? ahead[0].c.slug : info.layout.cabinets[0].slug;

    // 1. Signed out: watching.
    await page.waitForFunction(() => window.__hall.state.people && window.__hall.state.people.drawn >= 4, null, {timeout: 20000});
    await page.waitForTimeout(2500);
    const seen = await page.evaluate(() => ({stats: __hall.state.people,
      labels: [...document.querySelectorAll(".person-label")].map((e) => e.textContent),
      key: __hall.layout.layoutKey || HallPeople.layoutKey(__hall.layout.cabinets.map((c) => c.slug)),
      at: (() => { const f = HallPeople.figure("presence", "sess-3"); return f && f.atCabinet; })()}));
    check(label, "four people drawn", seen.stats.drawn === 4 && seen.stats.layers.presence === 4, seen.stats);
    check(label, "names show", seen.labels.length >= 2 && seen.labels.every((n) => NAMES.includes(n)), seen.labels);
    check(label, "one stands at a cabinet", seen.at === true, sim.atSlug);
    check(label, "polled with the layout key", sim.gets >= 2 && sim.lastKey === seen.key, {gets: sim.gets, key: sim.lastKey});
    check(label, "nothing sent while not opted in", sim.posts.length === 0, sim.posts.length);
    await page.screenshot({path: path.join(out, `${label}-people.png`)});

    await page.evaluate(() => { if (document.getElementById("help").hidden) document.getElementById("help-btn").click(); });
    await page.evaluate(() => { if (document.getElementById("settings").hidden) document.getElementById("settings-btn").click(); });
    await page.evaluate(() => document.getElementById("people-settings").scrollIntoView({block: "center"}));
    const out1 = await page.evaluate(() => {
      const a = document.getElementById("show-me-signin"), box = document.getElementById("set-show-me");
      return {disabled: box.disabled, checked: box.checked, href: a && a.href, h: a && a.getBoundingClientRect().height,
        see: document.getElementById("set-see-people").checked};
    });
    check(label, "signed out: off and disabled, with a sign-in link", out1.disabled && !out1.checked && out1.see && !!out1.href, out1);
    if (label === "iphone13") check(label, "sign-in link is a 44 px target", out1.h >= 44, out1.h);
    await page.screenshot({path: path.join(out, `${label}-settings-signed-out.png`)});
    // Following it goes to the sign-in page, to come back to this spot (the hash keeps it).
    const signin = page.waitForRequest((r) => r.url().startsWith(API + "/signin"), {timeout: 10000});
    await page.locator("#show-me-signin").click();
    const ret = new URL((await signin).url()).searchParams.get("return") || "";
    await page.waitForURL((u) => u.href.startsWith(API), {timeout: 10000}).catch(() => {});
    check(label, "sign-in returns to this spot", ret.startsWith(hallUrl) && /#p=-?[\d.]+,-?[\d.]+/.test(ret), ret);
    await page.goto(hallUrl + "?quality=0", {waitUntil: "commit"});

    // 2. Signed in (as if back from the sign-in page): opt in, and the pose goes out once a second.
    sim.signedIn = true;
    await page.goto(hallUrl + "?quality=0", {waitUntil: "commit"});
    await page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
    await page.waitForFunction(() => window.__hallPresence && window.__hallPresence.session && window.__hallPresence.session.signedIn, null, {timeout: 20000});
    await page.evaluate(() => { if (document.getElementById("help").hidden) document.getElementById("help-btn").click(); });
    await page.evaluate(() => { if (document.getElementById("settings").hidden) document.getElementById("settings-btn").click(); });
    await page.evaluate(() => document.getElementById("people-settings").scrollIntoView({block: "center"}));
    await page.locator("#set-show-me").check();
    await page.waitForFunction(() => window.__hallPresence.optedIn, null, {timeout: 10000});
    await page.screenshot({path: path.join(out, `${label}-settings-opted-in.png`)});
    const t0 = Date.now(), before = sim.posts.length;
    await page.waitForTimeout(4200);
    const posts = sim.posts.slice(before), rate = posts.length / ((Date.now() - t0) / 1000);
    const last = posts[posts.length - 1] && posts[posts.length - 1].body;
    check(label, "opted in with POST /v1/presence/optin", sim.optins.includes("POST"), sim.optins);
    check(label, "pose about once a second", rate > 0.7 && rate < 1.4, {posts: posts.length, rate: +rate.toFixed(2)});
    check(label, "pose is coarse and keyed", last && last.x % 0.25 === 0 && last.z % 0.25 === 0 && last.layout === seen.key
      && Object.keys(last).sort().join() === "cabinet,layout,x,yaw,z", last);
    const mine = await page.evaluate(() => ({fig: HallPeople.figure("presence", "sess-me"), stats: __hall.state.people}));
    check(label, "own entry not drawn", !mine.fig && mine.stats.layers.presence === 4, mine);

    // 3. See other people: off.
    await page.locator("#set-see-people").uncheck();
    const g0 = sim.gets;
    await page.waitForTimeout(2500);
    const off = await page.evaluate(() => ({stats: __hall.state.people, labels: document.querySelectorAll(".person-label").length,
      hidden: getComputedStyle(document.getElementById("people-labels") || document.body).visibility}));
    check(label, "see other people off: no polling, no figures", sim.gets === g0 && off.stats.drawn === 0, {gets: sim.gets - g0, off});
    await page.locator("#set-see-people").check();
    await page.evaluate(() => { if (!document.getElementById("help").hidden) document.getElementById("help-btn").click(); });
    await page.waitForTimeout(2500);
    await page.screenshot({path: path.join(out, `${label}-people-signed-in.png`)});
    check(label, "no page errors", errors.length === 0, errors.slice(0, 5));
    const fps = await page.evaluate(() => { const f0 = __hall.state.frames; return new Promise((r) => setTimeout(() => r((__hall.state.frames - f0) / 2), 2000)); });
    report[label].fps = fps;
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(path.join(out, "people.json"), JSON.stringify(report, null, 2));
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

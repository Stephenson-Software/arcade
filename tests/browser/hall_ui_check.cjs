// Checks the hall's people-facing UI in a real browser, against a mocked
// arcade-social, mocked activity (ghosts) and a mocked walk from today (replays).
//
//   NODE_PATH=<dir with playwright> node tests/browser/hall_ui_check.cjs <hall url> <out dir>
//
// <hall url> is a hall served by tools/hall_dev_server.py. Desktop and iPhone 13:
//   1. a tap (a click) on a figure shows its caption: a live person's name even
//      beyond the labels' usual 14 m, "A recent visitor" for a ghost, "A walk
//      from today" for a replay; it does not walk; a tap on the floor still walks;
//      on a desktop, the mouse over a figure shows it too;
//   2. the map shows everyone (presence, ghosts, replays), and "See other people"
//      and the ghosts setting take theirs off it;
//   3. the help panel with the settings open, at a cabinet, with "This device is
//      drawing slowly" up: it scrolls within the viewport, ends above the slow bar
//      and (on a phone) the play button, and does not lie over the card;
//   4. "You're visible": the pill in the bar shows only while opted in, fits the
//      bar (390 px), is a 44 px target on a phone, and opens the People settings.
// Writes screenshots and <out dir>/ui.json; exits 1 on a failed check.
const {chromium, devices} = require("playwright");
const fs = require("fs");
const path = require("path");
const W = require(path.join(__dirname, "..", "..", "src", "arcade", "hall_assets", "hall-walk.js"));

const API = "https://api.play.danielstephenson.dev";
const NAMES = ["Ada", "Bo", "Cyrus"];

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
    const sim = {optedIn: false, layout: null, me: null};
    const cors = {"access-control-allow-origin": origin, "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type, x-play-client, accept", "access-control-allow-methods": "GET, POST, DELETE",
      "content-type": "application/json"};
    const json = (route, body, status = 200, headers = cors) => route.fulfill({status, headers, body: JSON.stringify(body)});
    await ctx.route(API + "/**", async (route) => {
      const req = route.request(), url = new URL(req.url()), m = req.method();
      if (m === "OPTIONS") return route.fulfill({status: 204, headers: cors});
      if (url.pathname === "/v1/session") return json(route, {signedIn: true, displayName: "Ada Lovelace", signInUrl: API + "/signin"});
      if (url.pathname === "/v1/presence/me") return json(route, {optedIn: sim.optedIn});
      if (url.pathname === "/v1/presence/optin") { sim.optedIn = m === "POST"; return json(route, {optedIn: sim.optedIn}); }
      if (url.pathname === "/v1/presence" && m === "POST") return json(route, {ok: sim.optedIn, ttl: 10});
      if (url.pathname === "/v1/presence") return json(route, {people: people(sim), ttl: 10});
      return json(route, {}, 404);
    });
    // Ghosts: every cabinet a little busy.
    await ctx.route((u) => new URL(u).pathname.endsWith("/api/activity"), async (route) => {
      const res = await route.fetch(), body = await res.json();
      for (const k of Object.keys(body.levels || {})) body.levels[k] = 2;
      return json(route, body, 200, {"content-type": "application/json"});
    });
    // A walk from today: to and fro just left of straight ahead, 4 m out.
    await ctx.route((u) => new URL(u).pathname.endsWith("/api/walks/today"), async (route) => {
      for (let i = 0; i < 100 && !sim.me; i++) await new Promise((r) => setTimeout(r, 100));
      const walks = [];
      if (sim.me) {
        const me = sim.me, fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw), rx = -fz, rz = fx, pts = [];
        for (let k = 0; k < 40; k++) {
          const s = -1.6 + Math.abs((k % 20) - 10) * 0.08;
          pts.push([Math.round((me.x + fx * 4 + rx * s) * 4) / 4, Math.round((me.z + fz * 4 + rz * s) * 4) / 4]);
        }
        walks.push({layout: sim.key, points: pts, visits: []});
      }
      return json(route, {dt: 0.5, walks}, 200, {"content-type": "application/json"});
    });
    // Three people in front of where the visitor started, and one far off (past 14 m).
    function people(s) {
      if (!s.layout || !s.me) return [];
      const me = s.me, fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw), rx = -fz, rz = fx;
      const world = W.world(s.layout), list = [];
      [[3.5, -1.2], [5.5, 1.4], [8, -2.4]].forEach(([d, side], i) => {
        const p = W.resolve(me.x + fx * d + rx * side, me.z + fz * d + rz * side, world);
        list.push({id: "sess-" + i, name: NAMES[i], x: p.x, z: p.z, yaw: me.yaw + Math.PI, cabinet: null});
      });
      const far = W.resolve(me.x + fx * 16, me.z + fz * 16, world);
      list.push({id: "sess-far", name: "Faraway Fay", x: far.x, z: far.z, yaw: me.yaw + Math.PI, cabinet: null});
      return list;
    }

    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error" && !/^Failed to load resource/.test(m.text())) errors.push(m.text()); });
    const touch = !!opts.hasTouch;
    await page.goto(hallUrl + "?quality=0&replay=today", {waitUntil: "commit"});
    await page.waitForFunction(() => window.__hall && window.__hall.state.frames > 2, null, {timeout: 120000});
    const info = await page.evaluate(() => ({layout: __hall.layout, me: __hall.me,
      key: __hall.layout.layoutKey || HallPeople.layoutKey(__hall.layout.cabinets.map((c) => c.slug))}));
    sim.layout = info.layout; sim.key = info.key; sim.me = info.me;
    await page.waitForFunction(() => { const s = window.__hall.state.people; return s && s.layers.presence >= 3 && s.layers.ghosts >= 1 && s.layers.replays >= 1; }, null, {timeout: 30000})
      .catch(() => {});
    // The help opens by itself at first: closed, so the view is clear.
    await page.evaluate(() => { if (!document.getElementById("help").hidden) document.getElementById("help-btn").click(); });
    await page.waitForTimeout(1500);
    const stats0 = await page.evaluate(() => __hall.state.people);
    check(label, "presence, ghosts and a replay drawn", stats0 && stats0.layers.presence >= 3 && stats0.layers.ghosts >= 1 && stats0.layers.replays >= 1, stats0);

    // Where a figure is on screen (client px), mid-body, or null.
    const spot = (layer, id) => page.evaluate(([layer, id]) => {
      const f = HallPeople.figure(layer, id), cam = __hall.kit.cam, c = document.getElementById("hall");
      if (!f) return null;
      const v = {x: cam.tx, y: cam.ty, z: cam.tz, yaw: cam.yaw, pitch: cam.pitch, fov: __hall.settings.fov,
        aspect: c.clientWidth / c.clientHeight};
      const p = HallControls.project(v, [f.x, f.y + (layer === "presence" ? 0.8 : 0.75), f.z], 0.85);
      return p.on ? {x: (p.nx + 1) / 2 * c.clientWidth, y: (1 - p.ny) / 2 * c.clientHeight, d: Math.hypot(f.x - cam.tx, f.z - cam.tz)} : null;
    }, [layer, id]);
    const tapAt = async (x, y) => { if (touch) await page.touchscreen.tap(x, y); else await page.mouse.click(x, y); };
    const labels = () => page.evaluate(() => [...document.querySelectorAll(".person-label")]
      .filter((e) => getComputedStyle(e).visibility !== "hidden" && +e.style.opacity > 0).map((e) => e.textContent));
    // 1a. The far person: no label of their own; a tap shows the name, and does not walk.
    const meBefore = await page.evaluate(() => __hall.me);
    const before = await labels();
    const far = await spot("presence", "sess-far");
    check(label, "far person (past 14 m) has no label untapped", far && far.d > 14 && !before.includes("Faraway Fay"), {far, before});
    // A point of its column where nobody stands in front of it.
    let farAt = null;
    for (const dy of [0, -8, 8, -14, 14, -20]) {
      const hit = far && await page.evaluate(([x, y]) => __hall.kit.pickAt(x, y), [far.x, far.y + dy]);
      if (hit && hit.person && hit.person.id === "sess-far") { farAt = {x: far.x, y: far.y + dy}; break; }
    }
    check(label, "the far person can be picked", !!farAt, far);
    if (farAt) await tapAt(farAt.x, farAt.y);
    await page.waitForTimeout(700);
    const afterFar = {labels: await labels(), me: await page.evaluate(() => __hall.me), walking: await page.evaluate(() => __hall.state.walking),
      revealed: await page.evaluate(() => HallPeople.revealed)};
    check(label, "tap on a far person shows their name", afterFar.labels.includes("Faraway Fay") && afterFar.revealed.includes("presence:sess-far"), afterFar);
    check(label, "tap on a person does not walk", !afterFar.walking && Math.hypot(afterFar.me.x - meBefore.x, afterFar.me.z - meBefore.z) < 0.05, afterFar.me);
    await page.screenshot({path: path.join(out, `${label}-tap-person.png`)});

    // 1b. A ghost and a replay: their anonymous captions.
    async function tapLayer(layer, caption) {
      for (let tries = 0; tries < 12; tries++) {
        const r = await tapLayerOnce(layer, caption);
        if (r.ok) return r;
        await page.waitForTimeout(400);
      }
      return tapLayerOnce(layer, caption);
    }
    async function tapLayerOnce(layer, caption) {
      const cands = await page.evaluate((layer) => HallPeople.dots().filter((d) => d.layer === layer).map((d) => d.id), layer);
      const h = opts.viewport ? opts.viewport.height : 664;
      for (const id of cands) {
        const s = await spot(layer, id);
        if (!s || s.y < 110 || s.y > h - 170 || s.d > 20) continue;
        // Not when a person is in front of it at that point.
        const hit = await page.evaluate(([x, y]) => __hall.kit.pickAt(x, y), [s.x, s.y]);
        if (!hit || !hit.person || hit.person.layer !== layer) continue;
        await tapAt(s.x, s.y);
        await page.waitForTimeout(600);
        const ls = await labels();
        return {id, ok: ls.includes(caption), labels: ls};
      }
      return {ok: false, cands: cands.length};
    }
    const ghost = await tapLayer("ghosts", "A recent visitor");
    check(label, "tap on a ghost: 'A recent visitor'", ghost.ok, ghost);
    await page.screenshot({path: path.join(out, `${label}-tap-ghost.png`)});
    const replay = await tapLayer("replays", "A walk from today");
    check(label, "tap on a replay: 'A walk from today'", replay.ok, replay);
    await page.screenshot({path: path.join(out, `${label}-tap-replay.png`)});

    // 1c. Hover (desktop): the caption while over a figure, a pointer cursor.
    if (!touch) {
      await page.waitForTimeout(4200);  // the tapped captions time out
      const p = await spot("presence", "sess-far");
      if (p) await page.mouse.move(p.x, p.y);
      await page.waitForTimeout(400);
      const hov = {labels: await labels(), cls: await page.evaluate(() => document.getElementById("hall").className)};
      check(label, "hover shows a far person's name and a pointer", hov.labels.includes("Faraway Fay") && /on-figure/.test(hov.cls), hov);
      await page.mouse.move(5, 400);
      await page.waitForTimeout(300);
      const gone = await labels();
      check(label, "hover off: the name goes", !gone.includes("Faraway Fay"), gone);
    }

    // 1d. A tap on bare floor still walks there.
    const floor = await page.evaluate(() => {
      const c = document.getElementById("hall");
      for (let y = c.clientHeight * 0.72; y > c.clientHeight * 0.5; y -= 12) for (let x = c.clientWidth * 0.35; x < c.clientWidth * 0.65; x += 15) {
        const hit = __hall.kit.pickAt(x, y);
        if (hit && hit.floor && !hit.person) return {x, y};
      }
      return null;
    });
    if (floor) await tapAt(floor.x, floor.y);
    await page.waitForTimeout(250);
    const walked = await page.evaluate(() => __hall.state.walking || __hall.state.speed > 0);
    check(label, "tap on the floor still walks", !!floor && walked, floor);
    await page.waitForTimeout(2500);

    // 2. The map.
    await page.evaluate(() => { if (!__hall.map.on) document.getElementById("map-btn").click(); });
    await page.waitForTimeout(800);
    const map1 = await page.evaluate(() => __hall.state.mapPeople);
    check(label, "map: dots for presence, ghosts and replays", map1 && map1.presence >= 3 && map1.ghosts >= 1 && map1.replays >= 1, map1);
    await page.locator("#map").screenshot({path: path.join(out, `${label}-map.png`)});
    // A live person's dot is drawn in their colour.
    const dotColour = await page.evaluate(() => {
      const m = document.getElementById("map"), ctx = m.getContext("2d"), d = HallPeople.dots().find((x) => x.layer === "presence");
      const r = __hall.layout.room, pad = 8, k = Math.min((m.width - 2 * pad) / (2 * r.halfWidth), (m.height - 2 * pad) / (r.near - r.far));
      const oz = pad + (m.height - 2 * pad - (r.near - r.far) * k) / 2;
      const want = d.color.map((v) => Math.round(v * 255)), cx = Math.round(m.width / 2 + d.x * k), cy = Math.round(oz + (d.z - r.far) * k);
      const px = ctx.getImageData(cx - 3, cy - 3, 7, 7).data;
      let got = null, best = Infinity;
      for (let i = 0; i < px.length; i += 4) {
        const e = Math.abs(px[i] - want[0]) + Math.abs(px[i + 1] - want[1]) + Math.abs(px[i + 2] - want[2]);
        if (e < best) { best = e; got = [px[i], px[i + 1], px[i + 2]]; }
      }
      return {want, got};
    });
    check(label, "map: a person's dot in their colour", dotColour.want.every((v, i) => Math.abs(v - dotColour.got[i]) < 40), dotColour);
    // "See other people" off, and the ghosts off: theirs leave the map.
    await page.evaluate(() => {
      document.getElementById("help").hidden && document.getElementById("help-btn").click();
      document.getElementById("settings").hidden && document.getElementById("settings-btn").click();
    });
    await page.evaluate(() => { const s = document.getElementById("set-see-people"); s.checked = false; s.dispatchEvent(new Event("change")); });
    await page.evaluate(() => { const s = document.getElementById("set-ghosts"); s.checked = false; s.dispatchEvent(new Event("change", {bubbles: true})); });
    await page.evaluate(() => document.getElementById("help-btn").click());
    await page.waitForTimeout(2000);
    const map2 = await page.evaluate(() => __hall.state.mapPeople);
    check(label, "map: settings off take presence and ghosts off", map2 && map2.presence === 0 && map2.ghosts === 0 && map2.replays >= 1, map2);
    await page.locator("#map").screenshot({path: path.join(out, `${label}-map-off.png`)});
    await page.evaluate(() => {
      document.getElementById("help-btn").click();
      for (const id of ["set-see-people", "set-ghosts"]) { const s = document.getElementById(id); s.checked = true; s.dispatchEvent(new Event("change", {bubbles: true})); }
      document.getElementById("help-btn").click();
    });

    // 3. The help panel at a cabinet, with the settings open and the slow bar up.
    const slug = await page.evaluate(() => {
      const me = __hall.me;
      return __hall.layout.cabinets.filter((c) => c.deployed).map((c) => [Math.hypot(c.x - me.x, c.z - me.z), c.slug]).sort((a, b) => a[0] - b[0])[0][1];
    });
    await page.evaluate((s) => __hall.walkTo(s), slug);
    await page.waitForFunction((s) => __hall.near === s, slug, {timeout: 30000});
    await page.waitForTimeout(800);
    await page.evaluate(() => {
      if (document.getElementById("help").hidden) document.getElementById("help-btn").click();
      if (document.getElementById("settings").hidden) document.getElementById("settings-btn").click();
      StrataLoader.slow();
    });
    await page.waitForTimeout(400);
    const rect = (sel) => page.evaluate((sel) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, shown: cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.1};
    }, sel);
    const over = (a, b) => a && b && a.shown && b.shown && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    const L = {help: await rect("#help"), card: await rect("#card"), prompt: await rect("#prompt"), slow: await rect(".sk-slow"),
      stick: await rect("#stick"), vh: await page.evaluate(() => innerHeight)};
    check(label, "help: within the viewport, scrolling", L.help.bottom <= L.vh && await page.evaluate(() => {
      const h = document.getElementById("help"); return h.scrollHeight > h.clientHeight && getComputedStyle(h).overflowY === "auto"; }), L.help);
    check(label, "help: clear of the slow bar", !over(L.help, L.slow), {help: L.help, slow: L.slow});
    check(label, "help: clear of the play button", !over(L.help, L.prompt), {help: L.help, prompt: L.prompt});
    check(label, "help: not over the card", !over(L.help, L.card), {help: L.help, card: L.card});
    check(label, "slow bar: clear of the play button and the stick", !over(L.slow, L.prompt) && !over(L.slow, L.stick), L);
    await page.screenshot({path: path.join(out, `${label}-help-slow.png`)});
    // Its last row is reachable: scrolled to the end, "Reset to defaults" is inside the panel.
    await page.evaluate(() => { const h = document.getElementById("help"); h.scrollTop = h.scrollHeight; });
    await page.waitForTimeout(200);
    const reset = await rect("#set-reset"), help2 = await rect("#help");
    check(label, "help: last row reachable by scrolling", reset.bottom <= help2.bottom + 1 && reset.top >= help2.top, {reset, help: help2});
    await page.screenshot({path: path.join(out, `${label}-help-slow-scrolled.png`)});
    // The play button still plays (the prompt is the top element at its centre).
    const top = await page.evaluate(() => { const r = document.getElementById("prompt").getBoundingClientRect();
      const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e && (e.id || e.closest("#prompt") && "prompt-child"); });
    check(label, "play button not covered", top === "prompt" || top === "prompt-child", top);
    await page.evaluate(() => { document.querySelectorAll(".sk-slow").forEach((e) => e.remove()); });

    // 4. "You're visible".
    const pill = () => page.evaluate(() => {
      const p = document.getElementById("visible-pill"), r = p.getBoundingClientRect();
      return {hidden: p.hidden, text: p.textContent, aria: p.getAttribute("aria-label"), w: r.width, h: r.height, right: r.right, top: r.top};
    });
    const p0 = await pill();
    check(label, "visible pill hidden until opted in", p0.hidden, p0);
    await page.evaluate(() => document.getElementById("people-settings").scrollIntoView({block: "center"}));
    await page.locator("#set-show-me").check();
    await page.waitForFunction(() => window.__hallPresence.optedIn, null, {timeout: 10000});
    await page.evaluate(() => document.getElementById("help-btn").click());
    await page.waitForTimeout(300);
    const p1 = await pill();
    const bar = await page.evaluate(() => [...document.getElementById("bar").children]
      .filter((e) => !e.hidden && getComputedStyle(e).display !== "none" && getComputedStyle(e).position !== "fixed")
      .map((e) => { const r = e.getBoundingClientRect(); return {id: e.id, left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), h: Math.round(r.height)}; }));
    const vw = await page.evaluate(() => innerWidth);
    check(label, "visible pill shown when opted in, with the name for a screen reader",
      !p1.hidden && /Ada Lovelace/.test(p1.aria) && /visible/i.test(p1.aria), p1);
    if (!touch) check(label, "visible pill says the name", /Visible as Ada Lovelace/.test(p1.text), p1.text);
    check(label, "bar fits: nothing off screen, one line", bar.every((e) => e.left >= 0 && e.right <= vw) && new Set(bar.map((e) => e.top + e.h / 2)).size <= 2
      && (() => { const b2 = bar.filter((e) => e.id !== "where"); return Math.max(...b2.map((e) => e.top)) - Math.min(...b2.map((e) => e.top)) < 8; })(), bar);
    if (touch) check(label, "visible pill is a 44 px target", p1.w >= 44 && p1.h >= 44, p1);
    await page.screenshot({path: path.join(out, `${label}-visible-pill.png`)});
    await page.locator("#visible-pill").click();
    await page.waitForTimeout(300);
    const opened = await page.evaluate(() => ({help: !document.getElementById("help").hidden, settings: !document.getElementById("settings").hidden,
      focus: document.activeElement && document.activeElement.id}));
    check(label, "visible pill opens the People settings", opened.help && opened.settings && opened.focus === "set-show-me", opened);
    await page.screenshot({path: path.join(out, `${label}-visible-pill-opened.png`)});
    await page.locator("#set-show-me").uncheck();
    await page.waitForFunction(() => !window.__hallPresence.optedIn, null, {timeout: 10000});
    const p2 = await pill();
    check(label, "visible pill hidden after opting out", p2.hidden, p2);

    check(label, "no page errors", errors.length === 0, errors.slice(0, 5));
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(path.join(out, "ui.json"), JSON.stringify(report, null, 2));
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

"use strict";
/* Live presence in the hall (RFC 0030 §4): other players who chose to be
   seen, drawn by hall-people.js under their display names.

   Watching needs no account: while the hall is visible and "See other
   people" is on (the default), it asks arcade-social (the <meta
   name="arcade-social"> URL, https://api.<domain>) who is here, GET
   /v1/presence?layout=<key>, without credentials. Once a second while
   anyone is here, every 10 s while nobody is, every 3 s at least when the
   browser asks to save data, and never while the tab is hidden or the
   setting is off.

   Being seen is opt-in, per account, and off by default: "Show me in the
   hall" in the settings needs a signed-in player (signed out, it links to
   the service's sign-in page, which comes back to the same spot), and is
   kept by arcade-social (POST / DELETE /v1/presence/optin). Only while it is
   on and the hall is visible does the hall send its pose, once a second:
   POST /v1/presence {x, z, yaw, cabinet, layout}, x and z rounded to 0.25 m
   and yaw to 10 degrees, the cabinet being the one stood at or played
   (null elsewhere). arcade-social keeps it in memory for 10 s; nothing
   else about the visitor is sent.

   The layout key (HallPeople.layoutKey of the hall's cabinet order) keeps
   poses to halls whose cabinets stand in the same places.

   The pure parts are tested under node (tests/browser/hall_presence_test.cjs):
     HallPresence.parse(body)               -> [{id, name, x, z, yaw, cabinet}], malformed entries dropped
     HallPresence.figures(list, colorOf)    -> people for HallPeople.set("presence", ...)
     HallPresence.pose(me, cabinet, layout) -> the POST body (rounded), or null
     HallPresence.delay({anyone, saveData}) -> ms to the next poll
     HallPresence.notMe(list, sent, myId)   -> list without the visitor's own pose */
(function (root) {
  const SLUG = /^[a-z][a-z0-9-]{0,40}$/;
  const STEP = 0.25, YAW_STEP = Math.PI / 18;   // what a pose is rounded to
  const POLL = 1000, IDLE = 10000, SAVE_DATA = 3000, POST_EVERY = 1000;
  const STALE = 12000;                           // ms without an answer: nobody is shown
  const MAX = 64;

  const finite = (v) => typeof v === "number" && Number.isFinite(v);

  function parse(body) {
    const list = body && Array.isArray(body.people) ? body.people : [];
    const out = [];
    for (const p of list) {
      if (!p || typeof p !== "object") continue;
      const id = typeof p.id === "string" ? p.id.slice(0, 64) : "";
      if (!id || !finite(p.x) || !finite(p.z) || Math.abs(p.x) > 500 || Math.abs(p.z) > 500) continue;
      const name = typeof p.name === "string" ? p.name.replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 32) : "";
      out.push({id, name, x: p.x, z: p.z, yaw: finite(p.yaw) ? p.yaw : 0,
        cabinet: typeof p.cabinet === "string" && SLUG.test(p.cabinet) ? p.cabinet : null, you: p.you === true});
      if (out.length >= MAX) break;
    }
    return out;
  }

  function figures(list, colorOf) {
    return list.map((p) => ({id: p.id, x: p.x, z: p.z, yaw: p.yaw, color: colorOf(p.id), alpha: 1,
      label: p.name || "Player", cabinet: p.cabinet || undefined}));
  }

  const round = (v, step) => Math.round(v / step) * step;
  function pose(me, cabinet, layout) {
    if (!me || !finite(me.x) || !finite(me.z) || !layout) return null;
    let yaw = round(finite(me.yaw) ? me.yaw : 0, YAW_STEP) % (2 * Math.PI);
    if (yaw < 0) yaw += 2 * Math.PI;
    return {x: round(me.x, STEP), z: round(me.z, STEP), yaw: Math.round(yaw * 1000) / 1000,
      cabinet: typeof cabinet === "string" && SLUG.test(cabinet) ? cabinet : null, layout};
  }

  function delay(o) {
    const base = o && o.anyone ? POLL : IDLE;
    return o && o.saveData ? Math.max(base, SAVE_DATA) : base;
  }

  /* The visitor's own entry: the one the service marks ("you", or the id it
     gave back), else one at a pose this hall sent in the last few seconds. */
  function notMe(list, sent, myId) {
    return list.filter((p) => {
      if (p.you || (myId && p.id === myId)) return false;
      return !(sent || []).some((s) => Math.abs(s.x - p.x) < 1e-6 && Math.abs(s.z - p.z) < 1e-6
        && (s.cabinet || null) === (p.cabinet || null));
    });
  }

  const HallPresence = {parse, figures, pose, delay, notMe};
  if (typeof module !== "undefined" && module.exports) { module.exports = HallPresence; return; }
  root.HallPresence = HallPresence;

  /* ------------------------------------------------------- the page */
  const meta = document.querySelector('meta[name="arcade-social"]');
  const API = meta && /^https:\/\/[a-z0-9.-]+(:\d+)?$/.test(meta.content) ? meta.content : null;
  const settings = document.getElementById("settings");
  if (!API || !settings || typeof fetch !== "function") return;

  const SEE_KEY = "arcade-hall.people", INTENT_KEY = "arcade-hall.presence-intent";
  const store = {
    get(k, s) { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set(k, v, s) { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* blocked storage */ } },
    del(k, s) { try { (s ? sessionStorage : localStorage).removeItem(k); } catch (e) { /* blocked storage */ } },
  };
  const state = {see: store.get(SEE_KEY) !== "0", session: null, optedIn: false, busy: false, people: 0,
    polls: 0, posts: 0, lastOk: 0, myId: null, sent: [], error: null};
  root.__hallPresence = state;

  /* The two settings, after the hum. */
  const wrap = document.createElement("div");
  wrap.id = "people-settings";
  wrap.innerHTML = '<p class="people-head">People</p>'
    + '<label class="opt"><input id="set-see-people" type="checkbox"> See other people</label>'
    + '<label class="opt" id="show-me-row"><input id="set-show-me" type="checkbox" disabled> Show me in the hall</label>'
    + '<p id="show-me-hint" class="hint"></p>';
  const reset = document.getElementById("set-reset");
  settings.insertBefore(wrap, reset || null);
  const see = document.getElementById("set-see-people"), showMe = document.getElementById("set-show-me");
  const hint = document.getElementById("show-me-hint");
  see.checked = state.see;

  function layoutKey() {
    const l = root.__hall && root.__hall.layout;
    return l && root.HallPeople ? root.HallPeople.layoutKey(l.cabinets.map((c) => c.slug)) : null;
  }
  // Back to this spot after signing in: the hall keeps the visitor's place in the hash.
  function returnUrl() {
    const u = new URL(location.href);
    u.searchParams.delete("play");
    return u.href;
  }
  function render() {
    const s = state.session;
    if (!state.busy) showMe.checked = state.optedIn;
    showMe.disabled = !s || !s.signedIn || state.busy;
    hint.textContent = "";
    if (!s) {
      hint.textContent = "Showing yourself needs arcade-social, which isn't answering right now.";
    } else if (!s.signedIn) {
      const a = document.createElement("a");
      a.id = "show-me-signin";
      const href = () => `${s.signInUrl.split("?")[0]}?return=${encodeURIComponent(returnUrl())}`;
      a.href = href();
      a.textContent = "Sign in";
      // The place as it is now (the hall keeps it in the hash as the visitor walks).
      a.addEventListener("click", () => { a.href = href(); store.set(INTENT_KEY, String(Date.now()), true); });
      hint.append(a, " to appear to others, under your display name.");
    } else {
      hint.textContent = state.optedIn
        ? "Others see you here under your display name, while this hall is open."
        : "Off: you see others, nobody sees you.";
    }
    document.body.classList.toggle("people-off", !state.see);
  }

  async function call(path, opts) {
    try {
      const res = await fetch(API + path, Object.assign({headers: {accept: "application/json"}}, opts || {}));
      return res.ok ? await res.json() : null;
    } catch (e) { return null; }
  }
  const write = (method, body) => ({method, credentials: "include",
    headers: {"Content-Type": "application/json", "X-Play-Client": "1", accept: "application/json"},
    body: JSON.stringify(body || {})});

  async function refreshSession() {
    const s = await call("/v1/session", {credentials: "include"});
    if (!s || typeof s.signedIn !== "boolean") { state.session = null; render(); return; }
    state.session = {signedIn: s.signedIn,
      signInUrl: typeof s.signInUrl === "string" && s.signInUrl.startsWith(API + "/") ? s.signInUrl : API + "/signin"};
    if (s.signedIn) {
      const me = await call("/v1/presence/me", {credentials: "include"});
      state.optedIn = !!(me && me.optedIn === true);
      // Back from signing in after asking to be shown (in the last 10 minutes): finish what was asked.
      const intent = Number(store.get(INTENT_KEY, true));
      store.del(INTENT_KEY, true);
      if (!state.optedIn && intent && Date.now() - intent < 600000) await setOptIn(true);
    }
    render();
    if (state.optedIn) postSoon();
  }

  async function setOptIn(on) {
    state.busy = true; render();
    const r = await call("/v1/presence/optin", write(on ? "POST" : "DELETE"));
    if (r && typeof r.optedIn === "boolean") state.optedIn = r.optedIn;
    state.busy = false;
    if (!state.optedIn) state.sent = [];
    render();
    if (state.optedIn) postSoon();
  }
  showMe.addEventListener("change", () => setOptIn(showMe.checked));
  see.addEventListener("change", () => {
    state.see = see.checked;
    store.set(SEE_KEY, state.see ? "1" : "0");
    if (root.HallPeople) root.HallPeople.hide("presence", !state.see);
    if (!state.see && root.HallPeople) root.HallPeople.clear("presence");
    render();
    if (state.see) pollSoon();
  });

  /* Polling: one timer, rescheduled after each answer. */
  let pollTimer = null;
  function pollSoon(ms = 0) { clearTimeout(pollTimer); pollTimer = setTimeout(poll, ms); }
  async function poll() {
    pollTimer = null;
    if (document.hidden || !state.see) return;
    const started = Date.now(), key = layoutKey();
    if (!key) { pollSoon(500); return; }
    const body = await call(`/v1/presence?layout=${encodeURIComponent(key)}`);
    state.polls++;
    const now = Date.now();
    if (body) {
      state.lastOk = now;
      const list = notMe(parse(body), state.optedIn ? state.sent : [], state.myId);
      state.people = list.length;
      if (root.HallPeople && state.see) root.HallPeople.set("presence", figures(list, root.HallPeople.colorOf));
    } else if (now - state.lastOk > STALE && root.HallPeople) {
      state.people = 0;
      root.HallPeople.clear("presence");
    }
    const conn = navigator.connection;
    if (!document.hidden && state.see) pollSoon(Math.max(200, delay({anyone: state.people > 0 || state.optedIn, saveData: !!(conn && conn.saveData)}) - (Date.now() - started)));
  }

  let postTimer = null;
  function postSoon(ms = 0) { clearTimeout(postTimer); postTimer = setTimeout(post, ms); }
  async function post() {
    postTimer = null;
    if (document.hidden || !state.optedIn) return;
    const started = Date.now(), h = root.__hall, key = layoutKey();
    const body = h && key ? pose(h.me, h.playing || h.near, key) : null;
    if (body) {
      state.sent = state.sent.concat([body]).slice(-4);
      const r = await call("/v1/presence", write("POST", body));
      state.posts++;
      if (r && typeof r.id === "string") state.myId = r.id;
      // Refused (opted out elsewhere, signed out): stop sending until the setting says otherwise.
      if (r && r.ok === false) { state.optedIn = false; render(); return; }
    }
    if (!document.hidden && state.optedIn) postSoon(Math.max(200, POST_EVERY - (Date.now() - started)));
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(pollTimer); clearTimeout(postTimer); return; }
    pollSoon(); if (state.optedIn) postSoon();
  });

  render();
  if (root.HallPeople) root.HallPeople.hide("presence", !state.see);
  refreshSession();
  pollSoon(300);
})(typeof window !== "undefined" ? window : globalThis);

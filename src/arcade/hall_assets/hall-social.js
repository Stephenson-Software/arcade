"use strict";
/* The card's social line: a game's likes, the top of its first leaderboard
   and its achievements, from arcade-social (the <meta name="arcade-social">
   URL, https://api.<domain>; Stephenson-Software RFCs 0014 and 0015).

   Those reads are public and sent without credentials. The heart is a button
   only when the service answers this origin with credentials (GET
   /v1/session): signed in, it (or the L key) likes or unlikes the game; signed out, it goes
   to the service's sign-in page and comes back to this cabinet
   (/hall/?at=<slug>). When the service refuses this origin, is down or is
   slow, the card shows the count alone, or nothing: likes and boards are
   niceties, and the hall must work the same without them.

   hall.js says which cabinet the card is for with a "hall:card" event
   (detail: the slug, or null). The text is pure and tested under node
   (tests/browser/hall_social_test.cjs):

     HallSocial.parseCounts(body)        -> {slug: count}, malformed entries dropped
     HallSocial.likesText(n)             -> "1 like", "12 likes", "" for none
     HallSocial.valueText(board, value)  -> "12.4 seconds", "1 day", "1,024 wins"
     HallSocial.leaders(board, entries)  -> [{rank, name, value}], at most 3
     HallSocial.achievementsText(doc)    -> "3 achievements", "" for none */
(function (root) {
  const SLUG = /^[a-z][a-z0-9-]{1,30}$/;
  const TOP = 3, FRESH_MS = 60000;

  function isCount(v) { return typeof v === "number" && isFinite(v) && v >= 0; }

  function parseCounts(body) {
    const out = {};
    if (!body || typeof body !== "object" || Array.isArray(body)) return out;
    for (const [slug, n] of Object.entries(body)) if (SLUG.test(slug) && isCount(n)) out[slug] = Math.floor(n);
    return out;
  }

  function likesText(n) {
    if (!isCount(n) || n < 1) return "";
    return n === 1 ? "1 like" : `${Math.floor(n).toLocaleString("en-US")} likes`;
  }

  function valueText(board, value) {
    if (typeof value !== "number" || !isFinite(value)) return "";
    const whole = board && board.integer;
    const n = whole ? Math.round(value) : Math.round(value * 10) / 10;
    const num = n.toLocaleString("en-US", {maximumFractionDigits: whole ? 0 : 1});
    let unit = board && typeof board.unit === "string" ? board.unit.trim() : "";
    if (n === 1 && /[^s]s$/.test(unit)) unit = unit.slice(0, -1);
    return unit ? `${num} ${unit}` : num;
  }

  function leaders(board, entries) {
    if (!Array.isArray(entries)) return [];
    return entries
      .filter((e) => e && typeof e.displayName === "string" && e.displayName && typeof e.value === "number")
      .slice(0, TOP)
      .map((e) => ({rank: isCount(e.rank) ? e.rank : 0, name: e.displayName, value: valueText(board, e.value)}));
  }

  function achievementsText(doc) {
    const n = doc && Array.isArray(doc.achievements) ? doc.achievements.length : 0;
    return n ? (n === 1 ? "1 achievement" : `${n} achievements`) : "";
  }

  const HallSocial = {parseCounts, likesText, valueText, leaders, achievementsText};
  if (typeof module !== "undefined" && module.exports) { module.exports = HallSocial; return; }
  root.HallSocial = HallSocial;

  /* ------------------------------------------------------- the page */
  const meta = document.querySelector('meta[name="arcade-social"]');
  const API = meta && /^https:\/\/[a-z0-9.-]+$/.test(meta.content) ? meta.content : null;
  const box = document.getElementById("card-social");
  if (!API || !box || typeof fetch !== "function") return;

  const state = {counts: null, session: null, mine: null, slug: null, details: {}, busy: false};
  root.__hallSocial = state;

  async function getJson(path, credentials) {
    try {
      const res = await fetch(API + path, Object.assign({headers: {accept: "application/json"}},
        credentials ? {credentials: "include"} : {}));
      return res.ok ? await res.json() : null;
    } catch (e) { return null; }
  }

  async function refreshCounts() {
    const body = await getJson("/v1/likes/counts", false);
    if (body) { state.counts = parseCounts(body); render(); }
  }

  // Credentialed answers come only to origins the service allows; anywhere
  // else this stays null and the heart stays a plain count.
  async function refreshSession() {
    const s = await getJson("/v1/session", true);
    if (!s || typeof s.signedIn !== "boolean") return;
    state.session = {signedIn: s.signedIn,
      signInUrl: typeof s.signInUrl === "string" && s.signInUrl.startsWith(API + "/") ? s.signInUrl : API + "/signin"};
    if (s.signedIn) {
      const mine = await getJson("/v1/likes/me", true);
      state.mine = new Set(Array.isArray(mine) ? mine.filter((x) => typeof x === "string") : []);
    }
    render();
  }

  async function details(slug) {
    const had = state.details[slug];
    if (had && Date.now() - had.at < FRESH_MS) return;
    state.details[slug] = {at: Date.now(), board: null, top: [], achievements: ""};
    const [boards, ach] = await Promise.all([
      getJson(`/v1/games/${slug}/boards`, false), getJson(`/v1/games/${slug}/achievements`, false)]);
    const d = state.details[slug];
    d.achievements = achievementsText(ach);
    const board = boards && Array.isArray(boards.boards) ? boards.boards[0] : null;
    if (board && SLUG.test(board.id || "")) {
      const doc = await getJson(`/v1/boards/${slug}/${board.id}?limit=${TOP}`, false);
      d.board = board;
      d.top = leaders(board, doc && doc.entries);
    }
    if (state.slug === slug) render();
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function render() {
    const slug = state.slug;
    box.textContent = "";
    if (!slug) { box.hidden = true; return; }
    const count = state.counts ? state.counts[slug] || 0 : null;
    const line = el("div", "social-line");
    if (state.session) {
      const liked = !!(state.mine && state.mine.has(slug));
      const heart = el("button", "heart" + (liked ? " on" : ""));
      heart.type = "button";
      heart.setAttribute("aria-pressed", String(liked));
      heart.title = state.session.signedIn ? (liked ? "Unlike this game" : "Like this game") : "Sign in to like this game";
      heart.append(el("span", "h", liked ? "♥" : "♡"), el("span", "n", count ? String(count) : ""));
      heart.setAttribute("aria-label", `${liked ? "Unlike" : "Like"}${count ? ` (${likesText(count)})` : ""}`);
      heart.disabled = state.busy;
      heart.addEventListener("click", (ev) => { ev.stopPropagation(); toggle(slug); });
      line.append(heart);
    } else if (count) {
      line.append(el("span", "likes", `♥ ${likesText(count)}`));
    }
    const d = state.details[slug];
    if (d && d.achievements) line.append(el("span", "ach", d.achievements));
    if (line.childNodes.length) box.append(line);
    if (d && d.board && d.top.length) {
      const list = el("ol", "board");
      list.setAttribute("aria-label", d.board.title || "Leaderboard");
      list.append(el("li", "board-title", d.board.title || "Top scores"));
      for (const e of d.top) {
        const li = el("li");
        li.append(el("span", "r", `${e.rank}.`), el("span", "who", e.name), el("span", "v", e.value));
        list.append(li);
      }
      box.append(list);
    }
    box.hidden = !box.childNodes.length;
  }

  async function toggle(slug) {
    const s = state.session;
    if (!s || state.busy) return;
    if (!s.signedIn) {
      const back = new URL("./", location.href);
      back.search = ""; back.hash = "";
      back.searchParams.set("at", slug);
      location.assign(`${s.signInUrl.split("?")[0]}?return=${encodeURIComponent(back.href)}`);
      return;
    }
    const liked = state.mine && state.mine.has(slug);
    state.busy = true; render();
    try {
      const res = await fetch(`${API}/v1/likes/${slug}`, {method: liked ? "DELETE" : "POST", credentials: "include",
        headers: {"Content-Type": "application/json", "X-Play-Client": "1"}, body: "{}"});
      const body = res.ok ? await res.json() : null;
      if (body && typeof body.liked === "boolean") {
        if (body.liked) state.mine.add(slug); else state.mine.delete(slug);
        if (state.counts && isCount(body.count)) state.counts[slug] = body.count;
      }
    } catch (e) { /* the heart stays as it was */ }
    state.busy = false; render();
    const canvas = document.getElementById("hall");
    if (canvas) canvas.focus({preventScroll: true});
  }

  document.addEventListener("hall:card", (ev) => {
    const slug = ev.detail && SLUG.test(ev.detail) ? ev.detail : null;
    if (slug === state.slug) return;
    state.slug = slug;
    render();
    if (slug) details(slug);
  });
  // L likes the game at hand, as the heart does (only when the heart is there).
  addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "l" || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target && e.target.tagName) || document.body.classList.contains("playing")) return;
    if (state.slug && state.session) { e.preventDefault(); toggle(state.slug); }
  });
  refreshCounts();
  refreshSession();
  setInterval(() => { if (!document.hidden) refreshCounts(); }, FRESH_MS);
})(typeof window !== "undefined" ? window : globalThis);

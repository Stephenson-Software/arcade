/* "Share this spot": the link to where the visitor stands.

   At a cabinet, the link is /hall/?at=<slug>: it opens in front of that
   cabinet and unfurls with its own card (og:image). Anywhere else it is
   /hall/#p=<x>,<z>,<yaw>,<pitch>, the same place hall.js keeps in the URL.
   On a phone (coarse pointer) the system share sheet is offered when the
   browser has one (the Web Share API); otherwise the link is copied, with a
   short note to say so. Reads hall.js's state through window.__hall only. */
(function () {
  const button = document.getElementById("share");
  const toast = document.getElementById("toast");
  if (!button || !toast) return;
  const phone = matchMedia("(hover: none), (pointer: coarse)").matches;
  const state = {last: null};
  let hideAt = 0;

  function spot() {
    const h = window.__hall;
    const url = new URL("./", location.href);
    url.search = "";
    url.hash = "";
    const slug = h && h.near;
    const cab = slug && h.layout ? h.layout.cabinets.find((c) => c.slug === slug) : null;
    if (cab) {
      url.searchParams.set("at", cab.slug);
      return {url: url.href, title: `${cab.title}, in the Arcade Hall`, what: cab.title};
    }
    const me = h && h.me;
    if (me) url.hash = `p=${me.x.toFixed(3)},${me.z.toFixed(3)},${me.yaw.toFixed(5)},${me.pitch.toFixed(5)}`;
    return {url: url.href, title: "The Arcade Hall", what: null};
  }

  function say(text, ms, selectable) {
    ms = ms || 2600;
    toast.textContent = text;
    toast.classList.toggle("url", !!selectable);
    toast.hidden = false;
    // Next frame, so the fade-in runs after the element is shown.
    requestAnimationFrame(() => toast.classList.add("on"));
    hideAt = Date.now() + ms;
    setTimeout(() => {
      if (Date.now() < hideAt) return;
      toast.classList.remove("on");
      setTimeout(() => { if (Date.now() >= hideAt) toast.hidden = true; }, 300);
    }, ms + 50);
  }

  function copyByHand(text) {
    // For a page served without a secure context (a phone on the LAN), where
    // navigator.clipboard is missing.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:-100px;left:0;opacity:0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    return ok;
  }

  async function copy(s) {
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(s.url); ok = true; }
    } catch (e) { ok = false; }
    if (!ok) ok = copyByHand(s.url);
    if (ok) say(s.what ? `Link to ${s.what}'s cabinet copied` : "Link to this spot copied");
    else say(s.url, 9000, true);  // nothing could copy it: show it, to copy by hand
    state.last = {how: ok ? "copy" : "shown", url: s.url};
  }

  button.addEventListener("click", async () => {
    const s = spot();
    if (phone && navigator.share) {
      try {
        await navigator.share({title: s.title, url: s.url});
        state.last = {how: "share", url: s.url};
        return;
      } catch (e) {
        if (e && e.name === "AbortError") { state.last = {how: "cancelled", url: s.url}; return; }
        // Not allowed here (no share target, a permissions policy): copy instead.
      }
    }
    await copy(s);
  });
  window.__hallShare = {spot, state};
})();

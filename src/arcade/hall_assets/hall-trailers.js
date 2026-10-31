"use strict";
/* Live screens: the cabinets nearest the visitor play their game's trailer
   (clips/<slug>.mp4, tools/make_hall_clips.py) on their screen, silent, in
   place of the poster. Only one or two at a time (one on a phone or in
   economy), only screens in front of the visitor and facing them, none under
   reduced motion, and all of them paused while the page is hidden or a game
   is being played. A clip that cannot load or play leaves the poster.

   Which screens play is pure (the same under node, in
   tests/browser/hall_trailers_test.cjs):

     HallTrailers.pick(me, cabinets, {max, range, playing})
         -> the indexes of the cabinets to play, nearest first. me: {x, z, yaw};
            each cabinet {x, z, angle, clip, lit}; playing: the indexes playing
            now, kept a little further out (no flicker at the edge of range).
     HallTrailers.visible(me, c)   -> whether c's screen faces the visitor and
                                      is not behind them

   HallTrailers.screens(hooks) runs them in the page: hooks.upload(i, w, h, rgba)
   draws a frame to cabinet i's screen, hooks.restore(i) puts its poster back. */
(function (root) {
  const RANGE = 6.5, KEEP = 1.2, FRAME_S = 1 / 15;

  // A cabinet's screen faces +z in its own frame (hall-walk.js frame()).
  function facing(c) { return [Math.sin(c.angle || 0), Math.cos(c.angle || 0)]; }

  function visible(me, c) {
    const dx = me.x - c.x, dz = me.z - c.z, d = Math.hypot(dx, dz) || 1e-6;
    const [nx, nz] = facing(c);
    if ((dx * nx + dz * nz) / d < 0.05) return false;  // behind it, or side-on
    // In front of the visitor (the view looks along (-cos yaw, -sin yaw)), with some margin.
    const fx = -Math.cos(me.yaw), fz = -Math.sin(me.yaw);
    return (-dx * fx + -dz * fz) / d > -0.25;
  }

  function pick(me, cabinets, opts = {}) {
    const max = opts.max == null ? 2 : opts.max, range = opts.range || RANGE;
    const now = new Set(opts.playing || []);
    if (!me || max <= 0) return [];
    const out = [];
    cabinets.forEach((c, i) => {
      if (!c.clip || c.lit === false) return;
      const d = Math.hypot(c.x - me.x, c.z - me.z), reach = range + (now.has(i) ? KEEP : 0);
      // Kept a moment further out, the one playing does not flicker at the edge.
      if (d > reach || !visible(me, c)) return;
      out.push([d - (now.has(i) ? KEEP / 2 : 0), i]);
    });
    out.sort((a, b) => a[0] - b[0]);
    return out.slice(0, max).map((e) => e[1]);
  }

  /* --------------------------------------------------------- the page
     A frame is read from the video without stalling the hall's frame where
     the browser can (VideoFrame.copyTo, asynchronous, straight to RGBA),
     else drawn through a small canvas. Either way at the clip's own size
     (16:9, tools/make_hall_clips.py): the screen's texture takes that size
     while the clip plays, and the poster's again after. */
  function screens(hooks) {
    const live = new Map();  // cabinet index -> {video, at, t, shown, busy}
    let paused = false, ctx = null, copyRgba = typeof VideoFrame === "function";
    function surface(w, h) {
      if (!ctx) ctx = document.createElement("canvas").getContext("2d", {willReadFrequently: true});
      if (ctx.canvas.width !== w || ctx.canvas.height !== h) { ctx.canvas.width = w; ctx.canvas.height = h; }
      return ctx;
    }
    function start(i, c) {
      const v = document.createElement("video");
      v.muted = true; v.defaultMuted = true; v.loop = true; v.playsInline = true;
      v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
      v.preload = "auto";
      const rec = {video: v, at: -1, t: 0, shown: false, busy: false};
      v.addEventListener("error", () => stop(i));
      v.src = c.clip;
      live.set(i, rec);
      if (!paused) play(rec);
    }
    function play(rec) {
      const p = rec.video.play();
      if (p && p.catch) p.catch(() => { /* blocked (low-power mode): the poster stays */ });
    }
    function stop(i) {
      const rec = live.get(i);
      if (!rec) return;
      live.delete(i);
      rec.video.pause();
      rec.video.removeAttribute("src");
      try { rec.video.load(); } catch (e) { /* released */ }
      if (rec.shown) hooks.restore(i);
    }
    function shown(i, rec, w, h, rgba) {
      if (live.get(i) !== rec) return;  // stopped meanwhile
      hooks.upload(i, w, h, rgba);
      rec.shown = true;
    }
    async function grab(i, rec) {
      const v = rec.video;
      if (copyRgba) {
        let f = null;
        try {
          f = new VideoFrame(v);
          const r = f.visibleRect, w = r.width, h = r.height, rgba = new Uint8Array(w * h * 4);
          await f.copyTo(rgba, {rect: r, format: "RGBA"});
          shown(i, rec, w, h, rgba);
          return;
        } catch (e) {
          copyRgba = false;  // not here (an older browser): the canvas from now on
        } finally { if (f) f.close(); }
      }
      const w = v.videoWidth, h = v.videoHeight;
      if (!w || !h) return;
      const g = surface(w, h);
      g.drawImage(v, 0, 0, w, h);
      shown(i, rec, w, h, new Uint8Array(g.getImageData(0, 0, w, h).data.buffer));
    }
    return {
      // The screens that should play now (pick()'s answer).
      want(list) {
        const keep = new Set(list);
        for (const i of [...live.keys()]) if (!keep.has(i)) stop(i);
        for (const i of list) if (!live.has(i)) start(i, hooks.cabinet(i));
      },
      // Each frame: a new video frame, at most FRAME_S apart, onto its
      // screen. -> how many were started.
      draw(now) {
        let n = 0;
        if (paused) return n;
        for (const [i, rec] of live) {
          const v = rec.video;
          if (rec.busy || v.readyState < 2 || v.currentTime === rec.at || now - rec.t < FRAME_S * 1000) continue;
          rec.at = v.currentTime; rec.t = now; rec.busy = true; n++;
          grab(i, rec).catch(() => stop(i)).finally(() => { rec.busy = false; });
        }
        return n;
      },
      pause(p) {
        paused = !!p;
        for (const rec of live.values()) { if (paused) rec.video.pause(); else play(rec); }
      },
      has(i) { return live.has(i); },
      shown(i) { const r = live.get(i); return !!(r && r.shown); },
      get playing() { return [...live.keys()]; },
      get how() { return copyRgba ? "videoframe" : "canvas"; },
      stopAll() { for (const i of [...live.keys()]) stop(i); },
    };
  }

  const HallTrailers = {pick, visible, screens, RANGE, FRAME_S};
  if (typeof module !== "undefined" && module.exports) module.exports = HallTrailers;
  else root.HallTrailers = HallTrailers;
})(typeof window !== "undefined" ? window : globalThis);

"use strict";
/* The move from walking the hall to playing a game, and back, with no DOM
   and no engine, so the same code runs in the page and under node
   (tests/browser/hall_play_test.cjs).

     const m = HallPlay.machine({reduced});
     m.start(now, {from, to, how})  // from: the standing pose; to: HallPlay.screenPose(...);
                                    // how: "frame" | "navigate" | "switch"
     m.resume(now, {from, to})      // after the hall reloaded itself in the other
                                    // isolation mode, with the game open: parked at the screen
     m.loaded(now)                  // the game's frame has loaded and settled
     m.back(now)                    // Back to the hall
     m.skip(now)                    // Esc or a tap: finish the current move now
     m.update(now) -> {state, camera, frame, fade, locked, events}

   A pose is {x, y, z, yaw, pitch} (the eye, and the kit's yaw/pitch). The
   states, in order:

     idle -> in -> wait -> show -> playing -> hide -> out -> idle
                \-> leave (navigate/switch: fade to dark, then the page goes)

   in:   the camera eases from where the visitor stands to square-on in front
         of the cabinet's screen, close enough that the screen fills the view
         (the frame starts loading, hidden, as it begins);
   wait: parked at the screen until the game has painted (or WAIT_MAX);
   show: the frame crossfades in over the screen;
   hide: on Back, the frame fades out to the screen;
   out:  the camera eases back to where the visitor stood.

   Under reduced motion the camera does not move (camera is null: the hall
   keeps its own view) and the frame only fades.
   Input is locked in every state but idle and playing. update() returns
   the events that happened since the last call, once each:
   "load-frame", "frame-shown", "unload-frame", "navigate", "switch", "idle". */
(function (root) {
  const T = {in: 1.0, out: 1.0, show: 0.35, hide: 0.3, leave: 0.28, resume: 0.35};
  const T_REDUCED = {in: 0, out: 0, show: 0.2, hide: 0.2, leave: 0.18, resume: 0.2};
  const WAIT_MAX = 8;  // seconds: show the frame anyway

  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);

  function lerpPose(a, b, t) {
    const dy = Math.atan2(Math.sin(b.yaw - a.yaw), Math.cos(b.yaw - a.yaw));
    return {x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, z: a.z + (b.z - a.z) * t,
      yaw: a.yaw + dy * t, pitch: a.pitch + (b.pitch - a.pitch) * t};
  }

  /* The pose square-on to a cabinet's screen that fills a view of this aspect
     (width / height) and vertical fov (degrees). frame: HallWalk.frame(c);
     screen: layout.cabinet.screen [x0, y0, x1, y1, z]. */
  function screenPose(frame, screen, aspect, fov) {
    const [x0, y0, x1, y1, z] = screen;
    const t = Math.tan(fov * Math.PI / 360);
    const dh = (y1 - y0) / 2 / t, dw = (x1 - x0) / 2 / (t * aspect);
    const d = Math.min(dh, dw) * 0.97;  // covers the view: the screen's edges just out of sight
    const c = frame.p((x0 + x1) / 2, (y0 + y1) / 2, z + d);
    return {x: c[0], y: c[1], z: c[2], yaw: Math.atan2(frame.f[2], frame.f[0]), pitch: 0};
  }

  function machine(opts = {}) {
    const dur = opts.reduced ? T_REDUCED : T;
    let state = "idle", since = 0, from = null, to = null, how = null, ready = false, out = [];
    const go = (s, now) => { state = s; since = now; };
    const emit = (e) => out.push(e);
    const m = {
      get state() { return state; },
      get how() { return how; },
      start(now, o) {
        if (state !== "idle") return false;
        from = o.from; to = o.to; how = o.how || "frame"; ready = false;
        if (how === "frame") emit("load-frame");
        go("in", now);
        return true;
      },
      resume(now, o) {
        from = o.from; to = o.to; how = "frame"; ready = false;
        emit("load-frame");
        go("wait", now);
        m.resumed = now;
      },
      loaded(now) {
        if (how !== "frame" || ready) return;
        ready = true;
        if (state === "wait") go("show", now);
      },
      back(now) {
        if (state === "playing" || state === "show") go("hide", now);
        else if (state === "wait" || state === "in") {
          // Turn back from wherever the camera is now, without a jump.
          if (state === "in") to = lerpPose(from, to, easeInOut(clamp01(dur.in ? (now - since) / 1000 / dur.in : 1)));
          emit("unload-frame"); go("out", now);
        }
      },
      skip(now) {
        if (state === "in") go(how === "frame" ? (ready ? "show" : "wait") : "leave", now - (how === "frame" ? 0 : dur.leave));
        else if (state === "out") { go("idle", now); emit("idle"); }
        else if (state === "show") { go("playing", now); emit("frame-shown"); }
        else if (state === "hide") { emit("unload-frame"); go("out", now); }
      },
      update(now) {
        // Advance (more than once if a state's time ran out within this call).
        for (let guard = 0; guard < 8; guard++) {
          const e = (now - since) / 1000;
          if (state === "in" && e >= dur.in) {
            if (how === "frame") go(ready ? "show" : "wait", since + dur.in * 1000);
            else go("leave", since + dur.in * 1000);
          } else if (state === "wait" && (ready || e >= WAIT_MAX)) {
            go("show", ready ? now : since + WAIT_MAX * 1000);
          } else if (state === "show" && e >= dur.show) {
            go("playing", since + dur.show * 1000); emit("frame-shown");
          } else if (state === "hide" && e >= dur.hide) {
            emit("unload-frame"); go("out", since + dur.hide * 1000);
          } else if (state === "out" && e >= dur.out) {
            go("idle", since + dur.out * 1000); emit("idle");
          } else if (state === "leave" && e >= dur.leave) {
            emit(how === "switch" ? "switch" : "navigate"); go("gone", now);
          } else break;
        }
        const e = (now - since) / 1000;
        let camera = null, frame = 0, fade = 0;
        if (state === "in") camera = lerpPose(from, to, easeInOut(clamp01(dur.in ? e / dur.in : 1)));
        else if (state === "wait") camera = to;
        else if (state === "show") { camera = to; frame = clamp01(e / dur.show); }
        else if (state === "playing") { camera = to; frame = 1; }
        else if (state === "hide") { camera = to; frame = 1 - clamp01(e / dur.hide); }
        else if (state === "out") camera = lerpPose(to, from, easeInOut(clamp01(dur.out ? e / dur.out : 1)));
        else if (state === "leave" || state === "gone") { camera = to; fade = state === "gone" ? 1 : clamp01(e / dur.leave); }
        // After a reload into the other isolation mode: up from dark, at the screen.
        if (m.resumed != null) {
          const r = (now - m.resumed) / 1000;
          if (r < dur.resume) fade = Math.max(fade, 1 - clamp01(r / dur.resume));
          else m.resumed = null;
        }
        // Under reduced motion the camera stays where the visitor stands.
        if (opts.reduced) camera = null;
        const events = out;
        out = [];
        return {state, camera, frame, fade, locked: state !== "idle" && state !== "playing", events};
      },
    };
    return m;
  }

  const HallPlay = {machine, screenPose, lerpPose, easeInOut, T, T_REDUCED, WAIT_MAX};
  if (typeof module !== "undefined" && module.exports) module.exports = HallPlay;
  else root.HallPlay = HallPlay;
})(typeof window !== "undefined" ? window : globalThis);

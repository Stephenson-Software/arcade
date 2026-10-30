"use strict";
/* What keeps the hall alive while nobody plays: attract-mode screens, glowing
   marquees and an arcade's hum. The timing is pure (the same under node, in
   tests/browser/hall_life_test.cjs); the sound is WebAudio, made here, with no
   audio files.

     HallLife.attract(t, n)     -> the cabinet (index) showing its title card
                                   instead of its poster at scene time t, or -1
     HallLife.flicker(t, i)     -> a screen's brightness, 0.9..1: a faint CRT shimmer
     HallLife.pulse(t, i)       -> a marquee glow's strength, 0.7..1.3
     HallLife.scanlines(rgba, w, h) -> darkens every third row in place (a CRT look)
     HallLife.hum()             -> {on, set(on), pause(p)}: the hall's sound, off until set(true)
*/
(function (root) {
  const PERIOD = 6.5, SHOW = 2.4;  // seconds: one cabinet swaps to its title card for SHOW in every PERIOD

  // A fixed stride round the cabinets (coprime with their number), so every
  // one gets a turn, neighbours don't take turns in a row, and none twice running.
  function gcd(a, b) { while (b) [a, b] = [b, a % b]; return a; }
  function slotOf(k, n) {
    let step = Math.max(1, Math.floor(n * 0.618));
    while (n > 1 && gcd(step, n) !== 1) step++;
    return (k * step + 3) % n;
  }

  function attract(t, n) {
    if (n <= 0 || t < 0) return -1;
    const k = Math.floor(t / PERIOD), e = t - k * PERIOD;
    return e < SHOW ? slotOf(k, n) : -1;
  }

  function flicker(t, i) {
    const a = Math.sin(t * 7.3 + i * 1.7) * 0.5 + Math.sin(t * 13.1 + i * 0.9) * 0.3 + Math.sin(t * 2.1 + i * 2.3) * 0.2;
    return 0.95 + 0.05 * a;  // 0.9 .. 1.0
  }

  function pulse(t, i) {
    return 1 + 0.3 * Math.sin(t * 1.6 + i * 0.8);
  }

  function scanlines(rgba, w, h, every = 3, k = 0.86) {
    for (let y = 0; y < h; y += every) {
      for (let x = 0, p = y * w * 4; x < w; x++, p += 4) {
        rgba[p] = rgba[p] * k; rgba[p + 1] = rgba[p + 1] * k; rgba[p + 2] = rgba[p + 2] * k;
      }
    }
    return rgba;
  }

  /* The sound of an arcade: a low mains hum, cabinet fans (filtered noise),
     and now and then a far-off game's few chiptune notes. Quiet, and off
     until the visitor turns it on (the AudioContext is made on that tap). */
  function hum() {
    let ctx = null, master = null, timer = 0, on = false, paused = false;
    const AC = root.AudioContext || root.webkitAudioContext;
    function build() {
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0;
      master.connect(ctx.destination);
      for (const [f, g] of [[55, 0.22], [110, 0.08], [165, 0.03]]) {
        const o = ctx.createOscillator(), v = ctx.createGain();
        o.frequency.value = f; v.gain.value = g;
        o.connect(v).connect(master); o.start();
      }
      const len = ctx.sampleRate * 2, buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0);
      let last = 0;
      for (let i = 0; i < len; i++) { last = 0.97 * last + 0.03 * (Math.random() * 2 - 1); d[i] = last * 4; }
      const noise = ctx.createBufferSource(), lp = ctx.createBiquadFilter(), ng = ctx.createGain();
      noise.buffer = buf; noise.loop = true; lp.type = "lowpass"; lp.frequency.value = 500; ng.gain.value = 0.35;
      noise.connect(lp).connect(ng).connect(master); noise.start();
    }
    const SCALE = [523.25, 587.33, 659.25, 783.99, 880.0, 1046.5];
    function blip() {
      if (!ctx || !on || paused) return;
      const t0 = ctx.currentTime + 0.05, n = 2 + Math.floor(Math.random() * 4);
      const pan = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass"; lp.frequency.value = 1800;
      if (pan) { pan.pan.value = Math.random() * 1.6 - 0.8; lp.connect(pan).connect(master); } else lp.connect(master);
      for (let k = 0; k < n; k++) {
        const o = ctx.createOscillator(), g = ctx.createGain(), at = t0 + k * 0.09;
        o.type = "square";
        o.frequency.value = SCALE[Math.floor(Math.random() * SCALE.length)] / (Math.random() < 0.5 ? 2 : 1);
        g.gain.setValueAtTime(0, at);
        g.gain.linearRampToValueAtTime(0.05, at + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0005, at + 0.085);
        o.connect(g).connect(lp); o.start(at); o.stop(at + 0.1);
      }
    }
    function schedule() {
      clearTimeout(timer);
      if (!on || paused) return;
      timer = setTimeout(() => { blip(); schedule(); }, 1800 + Math.random() * 4200);
    }
    function level() {
      if (!ctx) return;
      const want = on && !paused ? 0.07 : 0;
      master.gain.cancelScheduledValues(ctx.currentTime);
      master.gain.setTargetAtTime(want, ctx.currentTime, 0.25);
      if (want > 0 && ctx.state === "suspended") ctx.resume();
    }
    return {
      get on() { return on; },
      get running() { return !!ctx && on && !paused; },
      set(v) {
        on = !!v;
        if (on && !ctx) {
          if (!AC) { on = false; return false; }
          try { build(); } catch (e) { on = false; return false; }
        }
        level(); schedule();
        return on;
      },
      pause(p) { paused = !!p; level(); schedule(); },
    };
  }

  const HallLife = {attract, flicker, pulse, scanlines, hum, PERIOD, SHOW};
  if (typeof module !== "undefined" && module.exports) module.exports = HallLife;
  else root.HallLife = HallLife;
})(typeof window !== "undefined" ? window : globalThis);

"use strict";
/* What keeps the hall alive while nobody plays: attract-mode screens, glowing
   marquees and an arcade's hum. The timing is pure (the same under node, in
   tests/browser/hall_life_test.cjs); the sound is WebAudio, made here, with no
   audio files.

     HallLife.attract(t, n)     -> the cabinet (index) showing its title card
                                   instead of its poster at scene time t, or -1
     HallLife.flicker(t, i)     -> a screen's brightness, 0.9..1: a faint CRT shimmer
     HallLife.pulse(t, i)       -> a marquee glow's strength, 0.7..1.3
     HallLife.candle(t, i)      -> a jack-o'-lantern's flame, 0.62..1 (seasonal decor)
     HallLife.scanlines(rgba, w, h) -> darkens every third row in place (a CRT look)
     HallLife.hum()             -> {on, set(on), pause(p), cabinets(list)}: the hall's sound,
                                   off until set(true)
     HallLife.tune(cabinet)     -> a cabinet's attract-mode loop: {wave, bpm, root, notes,
                                   cutoff}, the same every visit, flavoured by the game
     HallLife.spatial(me, c)    -> {gain, pan, muffle}: how a cabinet's loop reaches the
                                   visitor at me {x, z, yaw}, by distance and direction
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

  // A candle in a jack-o'-lantern: mostly steady, with quick uneven dips.
  function candle(t, i) {
    const a = Math.sin(t * 9.7 + i * 2.9) * 0.45 + Math.sin(t * 23.3 + i * 1.3) * 0.3 + Math.sin(t * 3.1 + i * 4.1) * 0.25;
    return 0.81 + 0.19 * a;  // 0.62 .. 1.0
  }

  /* ----------------------------------------- the cabinets' attract loops
     Each cabinet hums a short chiptune phrase of its own, made up from its
     slug (so it is the same every visit), in a flavour that suits the game:
     a text adventure (a tak game) a slow, soft, minor triangle-wave figure,
     a Halloween game a minor one, the rest a brighter pulse or bell
     arpeggio. Two bars playing, then two resting, so the floor never drones. */
  function hash(s) {
    let h = 2166136261;
    for (let k = 0; k < s.length; k++) { h ^= s.charCodeAt(k); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  const MAJOR = [0, 2, 4, 7, 9, 12, 14, 16], MINOR = [0, 3, 5, 7, 10, 12, 15, 17];
  const STEPS = 16;  // sixteenth notes in a bar; the phrase is two bars, then two rest
  function tune(c) {
    const slug = String(c && c.slug || ""), h = hash(slug), tags = (c && c.tags) || [];
    const text = c && c.engine === "tak", dark = text || tags.includes("halloween");
    const flavour = text ? "text" : ["pulse", "bell", "pulse", "bass"][h % 4];
    const wave = {text: "triangle", pulse: "square", bell: "sine", bass: "square"}[flavour];
    const scale = dark ? MINOR : MAJOR;
    // A root in A minor's / C major's neighbourhood, an octave by flavour.
    const root = 220 * Math.pow(2, (((h >>> 3) % 7) - 3) / 12) * (flavour === "bell" ? 2 : flavour === "bass" ? 0.5 : 1);
    const bpm = text ? 76 + (h >>> 7) % 14 : 104 + (h >>> 7) % 36;
    // 2 bars of sixteenths: a note (a scale degree) or a rest (-1). Sparse
    // for a text adventure, busier for an arcade game; always starts on the root.
    const notes = [];
    let r = h || 1;
    const rand = () => { r ^= r << 13; r ^= r >>> 17; r ^= r << 5; return (r >>> 0) / 4294967296; };
    const every = text ? 4 : 2, fill = text ? 0.55 : 0.75;
    for (let k = 0; k < 2 * STEPS; k++) {
      if (k === 0) { notes.push(0); continue; }
      notes.push(k % every === 0 && rand() < fill ? Math.floor(rand() * (flavour === "bass" ? 5 : scale.length)) : -1);
    }
    return {wave, flavour, bpm, root, scale, notes, cutoff: text ? 1100 : flavour === "bell" ? 2600 : 1800};
  }

  // The frequency of a tune's i-th note (a scale degree), or 0 for a rest.
  function noteHz(t, i) {
    const d = t.notes[i % t.notes.length];
    return d < 0 ? 0 : t.root * Math.pow(2, t.scale[d] / 12);
  }

  /* How a cabinet's loop reaches the visitor: louder near (a soft inverse
     square, out by about 11 m), panned to the side it is on (the view looks
     along (-cos yaw, -sin yaw); right is (sin yaw, -cos yaw)), and muffled
     from behind the cabinet, where its speaker faces away. */
  const HEAR = 11;
  function spatial(me, c) {
    const sx = c.x + Math.sin(c.angle || 0) * 0.4, sz = c.z + Math.cos(c.angle || 0) * 0.4;  // its speaker
    const dx = sx - me.x, dz = sz - me.z, d = Math.hypot(dx, dz);
    if (d > HEAR) return {gain: 0, pan: 0, muffle: 1};
    const fall = 1 / (1 + (d / 1.8) * (d / 1.8)), edge = Math.min(1, (HEAR - d) / 3);
    const rx = Math.sin(me.yaw), rz = -Math.cos(me.yaw);
    const pan = d < 1e-3 ? 0 : Math.max(-1, Math.min(1, (dx * rx + dz * rz) / d)) * 0.85;
    // Behind its screen: the speaker faces away.
    const behind = (me.x - c.x) * Math.sin(c.angle || 0) + (me.z - c.z) * Math.cos(c.angle || 0) < 0;
    return {gain: fall * edge * (behind ? 0.45 : 1), pan, muffle: behind ? 1 : 0};
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
    let cabBus = null, beatTimer = 0;
    const voices = new Map();  // id -> {tune, gain, lp, pan, step, at}
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
      // The cabinets' loops: their own bus, at their own level (each voice is placed by spatial()).
      cabBus = ctx.createGain();
      cabBus.gain.value = 0;
      cabBus.connect(ctx.destination);
    }
    const VOICE = 0.12, AHEAD = 0.3;
    function voice(id, t) {
      const g = ctx.createGain(), lp = ctx.createBiquadFilter();
      g.gain.value = 0;
      lp.type = "lowpass"; lp.frequency.value = t.cutoff;
      const pan = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
      lp.connect(g);
      if (pan) g.connect(pan).connect(cabBus); else g.connect(cabBus);
      // In step with the hall's clock, each on its own bar line.
      const sixteenth = 60 / t.bpm / 4;
      const v = {tune: t, gain: g, lp, pan, sixteenth, step: 0, at: ctx.currentTime + 0.1 + (hash(id) % 8) * sixteenth};
      voices.set(id, v);
      return v;
    }
    function dropVoice(id, v) {
      voices.delete(id);
      v.gain.gain.setTargetAtTime(0, ctx.currentTime, 0.15);
      setTimeout(() => { try { (v.pan || v.gain).disconnect(); } catch (e) { /* gone */ } }, 1500);
    }
    // Every 100 ms: the next AHEAD seconds of each voice's notes.
    function beat() {
      clearTimeout(beatTimer);
      beatTimer = 0;
      if (!ctx || !on || paused || !voices.size) return;
      const until = ctx.currentTime + AHEAD;
      for (const v of voices.values()) {
        if (v.at < ctx.currentTime) {  // fell behind (a hidden tab): skip ahead, in step
          const behind = Math.ceil((ctx.currentTime - v.at) / v.sixteenth);
          v.at += behind * v.sixteenth; v.step += behind;
        }
        while (v.at < until) {
          const phrase = v.step % (4 * STEPS);  // two bars playing, two resting
          const hz = phrase < 2 * STEPS ? noteHz(v.tune, phrase) : 0;
          if (hz) {
            const o = ctx.createOscillator(), e = ctx.createGain(), len = v.sixteenth * (v.tune.flavour === "text" ? 1.8 : 0.9);
            o.type = v.tune.wave; o.frequency.value = hz;
            e.gain.setValueAtTime(0, v.at);
            e.gain.linearRampToValueAtTime(1, v.at + 0.012);
            e.gain.exponentialRampToValueAtTime(0.001, v.at + len);
            o.connect(e).connect(v.lp); o.start(v.at); o.stop(v.at + len + 0.02);
          }
          v.at += v.sixteenth; v.step++;
        }
      }
      beatTimer = setTimeout(beat, 100);
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
      cabBus.gain.cancelScheduledValues(ctx.currentTime);
      cabBus.gain.setTargetAtTime(want > 0 ? 1 : 0, ctx.currentTime, 0.25);
      if (want > 0 && ctx.state === "suspended") ctx.resume();
      beat();
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
      /* The cabinets to hear now: [{id, tune, gain, pan, muffle}] (spatial()).
         Others fade out; each is eased to its new place. Nothing without sound. */
      cabinets(list) {
        if (!ctx || !on) return 0;
        const now = ctx.currentTime, keep = new Set();
        for (const c of list) {
          if (!(c.gain > 0.002)) continue;
          keep.add(c.id);
          const v = voices.get(c.id) || voice(c.id, c.tune);
          v.gain.gain.setTargetAtTime(VOICE * c.gain, now, 0.12);
          if (v.pan) v.pan.pan.setTargetAtTime(c.pan, now, 0.12);
          v.lp.frequency.setTargetAtTime(c.muffle ? 650 : v.tune.cutoff, now, 0.2);
        }
        for (const [id, v] of [...voices]) if (!keep.has(id)) dropVoice(id, v);
        if (!beatTimer) beat();
        return voices.size;
      },
      get voices() { return [...voices.keys()]; },
    };
  }

  const HallLife = {attract, flicker, pulse, candle, scanlines, hum, tune, spatial, noteHz, PERIOD, SHOW, HEAR};
  if (typeof module !== "undefined" && module.exports) module.exports = HallLife;
  else root.HallLife = HallLife;
})(typeof window !== "undefined" ? window : globalThis);

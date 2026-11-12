/* Sebas — interface logic.
   Python pushes events into window.Sebas.receive(); the page calls window.pywebview.api.*.
   Opened in a plain browser (no pywebview), it runs a demo; ?demo=<state> freezes a state. */
"use strict";

const $ = (s) => document.querySelector(s);
const SVGNS = "http://www.w3.org/2000/svg";
const params = new URLSearchParams(location.search);
const prefs = (() => { try { return JSON.parse(localStorage.getItem("sebas-prefs") || "{}"); } catch { return {}; } })();
const savePrefs = () => { try { localStorage.setItem("sebas-prefs", JSON.stringify(prefs)); } catch {} };

const STATE_TEXT = {
  idle: ["At Rest", "Say “Sebas, rise”, or ring the bell."],
  listening: ["Listening", "Pray, go on."],
  thinking: ["Considering", "One moment, if you please."],
  speaking: ["Speaking", ""],
};
const TOOL_TEXT = {
  system_status: "Inspecting the household systems", github_activity: "Consulting the GitHub ledger",
  vercel_deployments: "Reviewing the Vercel deployments", aws_instance_health: "Surveying the AWS estate",
  steam_wishlist: "Perusing the Steam wishlist", bookswagon_new_releases: "Browsing the Bookswagon shelves",
  morning_briefing: "Preparing the morning briefing", get_weather: "Observing the weather",
  open_app: "Opening an application", open_website: "Opening the browser", open_workspace: "Preparing your workspace",
  run_shortcut: "Performing a routine", set_volume: "Adjusting the volume", lock_screen: "Securing the screen",
  set_reminder: "Noting an engagement", list_reminders: "Reviewing the engagements",
  remember: "Committing to memory", forget: "Striking from memory",
};

/* ---------------- Sound (synthesised; no audio files) ---------------- */
const Sound = {
  ctx: null, on: prefs.sound !== false,
  ensure() {
    if (!this.ctx) { try { this.ctx = new AudioContext(); } catch { return null; } }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },
  tone(freq, dur, gain = 0.06, type = "sine", delay = 0) {
    const ctx = this.on && this.ensure(); if (!ctx) return;
    const t = ctx.currentTime + delay, o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + dur + 0.05);
  },
  tick() { // clockwork escapement
    const ctx = this.on && this.ensure(); if (!ctx) return;
    const len = Math.floor(ctx.sampleRate * 0.025), buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 6);
    const src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = 3200; f.Q.value = 3; g.gain.value = 0.35;
    src.connect(f).connect(g).connect(ctx.destination); src.start();
  },
  bell() { [[1318, 1.6, 0.05], [1976, 1.1, 0.025], [2637, 0.7, 0.015], [659, 1.9, 0.03]].forEach(([f, d, g]) => this.tone(f, d, g)); },
  chime(up = true) { const a = up ? [784, 1175] : [1175, 784]; this.tone(a[0], 0.35, 0.035); this.tone(a[1], 0.5, 0.03, "sine", 0.09); },
};

/* ---------------- Ambient dust ---------------- */
/* The ambient layer follows the seasons: sakura in spring, fireflies on summer
   nights, falling leaves in autumn, snow in winter, golden dust otherwise.
   ?season=spring|summer-night|autumn|winter|dust overrides it. */
function currentSeason() {
  const forced = params.get("season"); if (forced) return forced;
  const now = new Date(), m = now.getMonth() + 1, h = now.getHours();
  if (m === 12 || m <= 2) return "winter";
  if (m <= 5) return "spring";
  if (m <= 8) return h >= 18 || h < 6 ? "summer-night" : "dust";
  return "autumn";
}
const LEAF_COLOURS = ["#d9822b", "#b5501f", "#e0a83a", "#8c3b1d", "#c96a2c"];
function makeMote(kind, w, h, anywhere) {
  const d = devicePixelRatio, r = Math.random;
  const m = { x: r() * w, y: anywhere ? r() * h : -10 * d, p: r() * 6.28, a: r() * 6.28, spin: (r() - 0.5) * 0.06 };
  if (kind === "winter") Object.assign(m, { r: (r() * 1.6 + 0.8) * d, vy: (r() * 0.7 + 0.5) * d, vx: 0 });
  else if (kind === "spring") Object.assign(m, { r: (r() * 2 + 3) * d, vy: (r() * 0.5 + 0.45) * d, vx: (r() * 0.4 + 0.25) * d, c: r() < 0.5 ? "#f7b6c8" : "#ffd6e2" });
  else if (kind === "autumn") Object.assign(m, { r: (r() * 2.5 + 3.5) * d, vy: (r() * 0.6 + 0.55) * d, vx: (r() - 0.3) * 0.4 * d, c: LEAF_COLOURS[Math.floor(r() * LEAF_COLOURS.length)] });
  else if (kind === "summer-night") Object.assign(m, { y: r() * h, r: (r() * 1.4 + 1.2) * d, vy: 0, vx: 0 });
  else Object.assign(m, { y: anywhere ? r() * h : h + 5, r: (r() * 1.4 + 0.3) * d, vy: -(r() * 0.25 + 0.05) * d, vx: 0, gold: r() < 0.75 });
  return m;
}
function startDust() {
  const c = $("#dust"), g = c.getContext("2d"), kind = currentSeason();
  document.body.dataset.season = kind;
  const count = { "summer-night": 26, spring: 40, autumn: 34, winter: 60, dust: 70 }[kind] || 60;
  let motes = [];
  const size = () => {
    c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
    motes = Array.from({ length: count }, () => makeMote(kind, c.width, c.height, true));
  };
  size(); addEventListener("resize", size);
  let lastDust = 0;
  (function frame(t) {
    // 30 fps is plenty for drifting particles; nothing is drawn while hidden or minimised
    if (document.body.dataset.ambient !== "off" && !document.hidden && !document.body.classList.contains("gaming") && t - lastDust > 33) {
      lastDust = t;
      g.clearRect(0, 0, c.width, c.height);
      for (let i = 0; i < motes.length; i++) {
        const m = motes[i];
        if (kind === "summer-night") { // fireflies wander and pulse
          m.a += (Math.random() - 0.5) * 0.3; m.x += Math.cos(m.a) * 0.6 * devicePixelRatio; m.y += Math.sin(m.a) * 0.4 * devicePixelRatio;
          if (m.x < 0 || m.x > c.width || m.y < 0 || m.y > c.height) motes[i] = makeMote(kind, c.width, c.height, true);
          const glow = Math.max(0, Math.sin(t / 700 + m.p * 3));
          g.globalAlpha = 0.15 + 0.85 * glow; g.shadowBlur = 14 * devicePixelRatio; g.shadowColor = "#dfff6e";
          g.fillStyle = "#e9ff8a"; g.beginPath(); g.arc(m.x, m.y, m.r, 0, 6.283); g.fill(); g.shadowBlur = 0;
          continue;
        }
        m.y += m.vy; m.x += m.vx + Math.sin(t / 1800 + m.p) * 0.35 * devicePixelRatio; m.a += m.spin;
        if (m.y > c.height + 12 || m.y < -14 * devicePixelRatio || m.x > c.width + 12) { motes[i] = makeMote(kind, c.width, c.height, false); continue; }
        if (kind === "winter") {
          g.globalAlpha = 0.75; g.fillStyle = "#f4f8ff"; g.beginPath(); g.arc(m.x, m.y, m.r, 0, 6.283); g.fill();
        } else if (kind === "spring" || kind === "autumn") {
          g.save(); g.translate(m.x, m.y); g.rotate(m.a); g.globalAlpha = kind === "spring" ? 0.8 : 0.85; g.fillStyle = m.c;
          g.beginPath(); g.ellipse(0, 0, m.r, m.r * (kind === "spring" ? 0.62 : 0.45), 0, 0, 6.283); g.fill();
          if (kind === "autumn") { g.strokeStyle = "rgba(60,25,10,0.6)"; g.lineWidth = 0.8 * devicePixelRatio; g.beginPath(); g.moveTo(-m.r, 0); g.lineTo(m.r * 1.3, 0); g.stroke(); }
          g.restore();
        } else {
          g.globalAlpha = 0.25 + 0.35 * Math.abs(Math.sin(t / 1400 + m.p));
          g.fillStyle = m.gold ? "#e6c77f" : "#7ff0e4"; g.beginPath(); g.arc(m.x, m.y, m.r, 0, 6.283); g.fill();
        }
      }
    }
    requestAnimationFrame(frame);
  })(0);
}

/* ---------------- Avatar rings ---------------- */
function el(tag, attrs, parent) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent && parent.appendChild(e); return e; }
function buildRings() {
  const cx = 200, cy = 200, outer = $("#ring-outer"), gear = $("#ring-gear"), sun = $("#sunburst");
  for (let i = 0; i < 120; i++) { // minute ticks
    const a = (i / 120) * Math.PI * 2, long = i % 10 === 0, r1 = 182, r2 = long ? 168 : 177;
    el("line", { x1: cx + r1 * Math.cos(a), y1: cy + r1 * Math.sin(a), x2: cx + r2 * Math.cos(a), y2: cy + r2 * Math.sin(a),
      stroke: long ? "#f1d892" : "#c9a45c", "stroke-opacity": long ? 0.9 : 0.45, "stroke-width": long ? 1.6 : 0.8 }, outer);
  }
  ["XII", "III", "VI", "IX"].forEach((n, i) => { // engraved numerals
    const a = (i / 4) * Math.PI * 2 - Math.PI / 2, r = 157;
    const t = el("text", { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) + 3.5, "text-anchor": "middle", "font-family": "Cinzel, serif",
      "font-size": 10, fill: "#c9a45c", "fill-opacity": 0.7, "letter-spacing": 1 }, outer); t.textContent = n;
  });
  let d = ""; const teeth = 48, rIn = 140, rOut = 147; // gear wheel
  for (let i = 0; i < teeth; i++) {
    const a0 = (i / teeth) * 6.2832, a1 = a0 + 6.2832 / teeth * 0.45, a2 = a0 + 6.2832 / teeth * 0.55, a3 = a0 + 6.2832 / teeth;
    const p = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
    d += `${i ? "L" : "M"}${p(rIn, a0)} L${p(rOut, a1)} L${p(rOut, a2)} L${p(rIn, a3)} `;
  }
  el("path", { d: d + "Z", fill: "none", stroke: "#c9a45c", "stroke-opacity": 0.28, "stroke-width": 1 }, gear);
  for (let i = 0; i < 36; i++) { // sunburst
    const a = (i / 36) * Math.PI * 2;
    el("line", { x1: cx + 60 * Math.cos(a), y1: cy + 60 * Math.sin(a), x2: cx + 136 * Math.cos(a), y2: cy + 136 * Math.sin(a), "stroke-width": i % 2 ? 0.6 : 1.4 }, sun);
  }
}

/* ---------------- State, voice envelope and halo ---------------- */
const live = { state: "idle", mic: 0, micShown: 0, envelope: [], envStart: 0, envStep: 0.04, amp: 0, thinkStart: 0 };
function setState(state) {
  if (!STATE_TEXT[state] || state === live.state) return;
  const prev = live.state; live.state = state; document.body.dataset.state = state;
  const [cap, hint] = STATE_TEXT[state]; $("#caption").textContent = cap; $("#hint").textContent = hint; $("#state-label").textContent = cap;
  if (state === "listening") Sound.chime(true);
  else if (state === "thinking") { Sound.tick(); live.thinkStart = performance.now(); }
  else if (state === "idle" && prev === "speaking") Sound.chime(false);
}
function currentAmp(now) {
  if (live.state !== "speaking" || !live.envelope.length) return 0;
  const i = Math.floor((now - live.envStart) / 1000 / live.envStep);
  return i >= 0 && i < live.envelope.length ? live.envelope[i] : 0;
}
/* The butler's snappy, frame-based animation. Every part switches between held
   poses (no tweening): mouth shapes from the voice envelope, irregular blinks,
   glances, an arched brow now and then, arm poses per state, and gestures. */
const butler = { el: null, frame: -1, nextBlink: 0, blinkUntil: 0, lastSwap: 0, nextGlance: 0,
  nextArch: 0, nextGesture: 0, poseUntil: 0, smileUntil: 0, lastState: "idle" };
const GAZES = [[0, 0], [0, 0], [-2, 0], [2, 0], [-1.5, 1], [1.5, -0.8], [0, -1]];
function flag(name, on) { if (on) butler.el.setAttribute(name, ""); else butler.el.removeAttribute(name); }
function pulse(name, ms) { flag(name, true); setTimeout(() => flag(name, false), ms); }
function setPose(pose, ms) { butler.el.dataset.pose = pose; butler.poseUntil = ms ? performance.now() + ms : 0; }
function look(dx, dy) { $("#irises").style.transform = `translate(${dx}px, ${dy}px)`; }
function gesture(name, ms = 1300) {
  if (!butler.el) return;
  butler.el.dataset.gesture = name; setPose("chest");
  setTimeout(() => { if (butler.el.dataset.gesture === name) delete butler.el.dataset.gesture; }, ms);
}
function animateButler(now) {
  const b = butler; if (!b.el) b.el = $("#bust");
  const s = live.state;
  if (s !== b.lastState) { // pose changes on entering a state
    if (s === "thinking") { setPose("glasses", 1400); look(2, -1.5); }
    else if (s === "listening") { setPose("chest"); look(0, 0); }
    else if (s === "speaking") { pulse("data-nod", 260); b.nextGesture = now + 900; }
    else if (s === "idle" && b.lastState === "speaking") b.smileUntil = now + 1300;
    b.lastState = s;
  }
  if (now - b.lastSwap > 70) { // mouth frames at ~14 fps for a hand-drawn feel
    b.lastSwap = now;
    const raw = s === "speaking" ? currentAmp(now) : 0;
    const frame = s !== "speaking" && now < b.smileUntil ? "smile" : raw < 0.12 ? 0 : raw < 0.4 ? 1 : raw < 0.7 ? 2 : 3;
    if (frame !== b.frame) { b.frame = frame; b.el.dataset.mouth = frame; }
    flag("data-emph", frame === 3);
  }
  if (b.poseUntil && now > b.poseUntil) setPose("chest");
  if (s === "speaking" && now > b.nextGesture) { // an open-palm gesture now and then
    if (Math.random() < 0.45) setPose("present", 1500);
    b.nextGesture = now + 2600 + Math.random() * 2200;
  }
  if (!b.nextBlink) { b.nextBlink = now + 2000; b.nextGlance = now + 2500; b.nextArch = now + 15000; }
  if (now > b.nextBlink) { // blink at irregular intervals, sometimes twice
    flag("data-blink", true); b.blinkUntil = now + 110;
    b.nextBlink = now + (Math.random() < 0.2 ? 260 : 2400 + Math.random() * 3600);
  }
  if (b.blinkUntil && now > b.blinkUntil) { flag("data-blink", false); b.blinkUntil = 0; }
  if (now > b.nextGlance && (s === "idle" || s === "speaking")) { // glance about
    const [dx, dy] = s === "speaking" ? [0, 0] : GAZES[Math.floor(Math.random() * GAZES.length)];
    look(dx, dy); b.nextGlance = now + 1500 + Math.random() * 2800;
  }
  if (now > b.nextArch) { // the dry-wit eyebrow
    if (s === "idle" || s === "speaking") { b.el.dataset.brow = "arch"; setTimeout(() => delete b.el.dataset.brow, 1100); }
    b.nextArch = now + 12000 + Math.random() * 14000;
  }
}
function startHalo() {
  const c = $("#halo"), g = c.getContext("2d"), bars = 96;
  const size = () => { const r = c.getBoundingClientRect(); c.width = Math.max(1, r.width * devicePixelRatio); c.height = Math.max(1, r.height * devicePixelRatio); };
  size(); new ResizeObserver(size).observe(c.parentElement);
  let lastHalo = 0;
  (function frame(now) {
    // 30 fps while active, 15 at rest, nothing while hidden: the halo was the
    // interface's main CPU cost when redrawn at the screen's full refresh rate
    const interval = live.state === "idle" && live.micShown < 0.05 ? 66 : 33;
    if (document.hidden || document.body.classList.contains("gaming") || now - lastHalo < interval) { requestAnimationFrame(frame); return; }
    lastHalo = now;
    const w = c.width, h = c.height, cx = w / 2, cy = h / 2, R = w * 0.335;
    g.clearRect(0, 0, w, h);
    live.amp += (currentAmp(now) - live.amp) * 0.35;
    live.micShown += (live.mic - live.micShown) * 0.25;
    const s = live.state, t = now / 1000;
    const color = s === "listening" ? "95,227,214" : s === "speaking" ? "241,216,146" : "201,164,92";
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2 - Math.PI / 2;
      let v;
      if (s === "speaking") v = live.amp * (0.55 + 0.45 * Math.abs(Math.sin(i * 0.9 + t * 9))) ;
      else if (s === "listening") v = Math.max(live.micShown, 0.08) * (0.5 + 0.5 * Math.abs(Math.sin(i * 1.7 + t * 6)));
      else if (s === "thinking") { const head = (t * 1.6) % 1, d = ((i / bars) - head + 1) % 1; v = Math.max(0, 1 - d * 4) * 0.55; }
      else v = 0.06 + 0.05 * Math.sin(t * 1.2 + i * 0.26) ** 2 + live.micShown * 0.5;
      const len = (6 + v * 46) * devicePixelRatio;
      g.strokeStyle = `rgba(${color},${0.25 + v * 0.75})`; g.lineWidth = 2 * devicePixelRatio; g.lineCap = "round";
      g.beginPath(); g.moveTo(cx + R * Math.cos(a), cy + R * Math.sin(a)); g.lineTo(cx + (R + len) * Math.cos(a), cy + (R + len) * Math.sin(a)); g.stroke();
    }
    const glow = g.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.25); // aura
    const ga = s === "speaking" ? 0.12 + live.amp * 0.18 : s === "listening" ? 0.1 + live.micShown * 0.2 : 0.07;
    glow.addColorStop(0, `rgba(${color},${ga})`); glow.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = glow; g.fillRect(0, 0, w, h);
    animateButler(now);
    $("#mic-meter").style.width = `${Math.round(live.micShown * 100)}%`;
    requestAnimationFrame(frame);
  })(0);
}

/* ---------------- Brass dial gauges ---------------- */
const dials = {};
function buildDials() {
  [["battery", "Battery"], ["cpu", "Engine"], ["memory", "Memory"]].forEach(([key, label]) => {
    const wrap = document.createElement("div"); wrap.className = "dial";
    const svg = el("svg", { viewBox: "0 0 100 84" }, wrap);
    el("circle", { cx: 50, cy: 52, r: 40, fill: "rgba(8,12,22,0.9)", stroke: "url(#dialRim)", "stroke-width": 2.4 }, svg);
    const defs = el("defs", {}, svg), rim = el("linearGradient", { id: "dialRim", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: 0, "stop-color": "#f6e2a4" }, rim); el("stop", { offset: 1, "stop-color": "#7a5a26" }, rim);
    for (let i = 0; i <= 20; i++) { // scale from -120deg to +120deg
      const a = ((-120 + i * 12) - 90) * Math.PI / 180, long = i % 5 === 0, r1 = 35, r2 = long ? 28 : 31;
      el("line", { x1: 50 + r1 * Math.cos(a), y1: 52 + r1 * Math.sin(a), x2: 50 + r2 * Math.cos(a), y2: 52 + r2 * Math.sin(a),
        stroke: i >= 16 ? "#e0705a" : "#c9a45c", "stroke-width": long ? 1.6 : 0.8 }, svg);
    }
    const needle = el("g", { class: "needle" }, svg);
    el("path", { d: "M50 52 L48.4 50 L50 20 L51.6 50 Z", fill: "#5fe3d6", filter: "url(#glowCyan)" }, needle);
    el("circle", { cx: 50, cy: 52, r: 4, fill: "#c9a45c", stroke: "#f6e2a4", "stroke-width": 0.8 }, svg);
    el("path", { class: "crack", d: "M50 14 L46 27 L53 34 L47 46 M53 34 L63 39 L68 47 M46 27 L36 24" }, svg); // for "power level"
    const lab = document.createElement("div"); lab.className = "label"; lab.textContent = label;
    const val = document.createElement("div"); val.className = "value"; val.textContent = "—";
    wrap.append(lab, val); $("#dials").appendChild(wrap);
    dials[key] = { needle, val }; setDial(key, 0, "—");
  });
}
function setDial(key, pct, text) {
  const d = dials[key]; if (!d) return;
  d.needle.style.transform = `rotate(${-120 + Math.max(0, Math.min(100, pct)) * 2.4}deg)`; d.val.textContent = text;
}

/* ---------------- Ledger, ticker, household ---------------- */
const fmtTime = (d = new Date()) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function addEntry(role, text) {
  $("#ledger-empty")?.remove();
  const e = document.createElement("div"); e.className = `entry ${role}`;
  if (role !== "notice") { const m = document.createElement("div"); m.className = "meta"; m.textContent = `${role === "user" ? "You" : "Sebas"} · ${fmtTime()}`; e.appendChild(m); }
  const t = document.createElement("div"); t.className = "text"; t.textContent = text; e.appendChild(t);
  const list = $("#ledger"); list.appendChild(e); while (list.children.length > 80) list.firstChild.remove();
  list.scrollTop = list.scrollHeight;
}
const openTools = {};
function toolEvent({ phase, tool, success }) {
  const ticker = $("#ticker");
  if (phase === "start") {
    const line = document.createElement("div"); line.className = "tick-line"; line.textContent = `${TOOL_TEXT[tool] || tool.replace(/_/g, " ")}…`;
    ticker.appendChild(line); while (ticker.children.length > 4) ticker.firstChild.remove();
    (openTools[tool] ||= []).push(line); Sound.tick();
  } else {
    const line = (openTools[tool] || []).shift(); if (!line) return;
    line.classList.add(success ? "done" : "failed");
    setTimeout(() => { line.style.transition = "opacity 1s"; line.style.opacity = 0; setTimeout(() => line.remove(), 1000); }, 6000);
  }
}
function setMode(mode, model) {
  const b = $("#mode-badge");
  b.classList.toggle("local", mode === "local");
  b.textContent = mode === "local" ? `Local · ${(model || "").replace(":latest", "")}` : mode === "cloud" ? `Gemini · key ${(model || "").split("key ")[1] || 1}` : "Waking";
  $("#mind-engine").textContent = mode === "local" ? `${model} (local)` : mode === "cloud" ? (model || "Gemini") : "—";
  $("#tel-mind").textContent = mode === "local" ? "LOCAL" : mode === "cloud" ? "CLOUD" : "—";
}
function relTime(sec) { const m = Math.max(0, Math.round((sec * 1000 - Date.now()) / 60000)); return m < 1 ? "now" : m < 60 ? `in ${m} min` : `in ${Math.floor(m / 60)} h ${m % 60} m`; }
function fillList(id, items, empty, render) {
  const ul = $(id); ul.replaceChildren();
  if (!items.length) { const li = document.createElement("li"); li.className = "empty"; li.textContent = empty; ul.appendChild(li); return; }
  items.forEach((it) => ul.appendChild(render(it)));
}
let lastSnapshot = null;
function applySnapshot(s) {
  if (!s) return;
  lastSnapshot = s;
  if (s.mode) setMode(s.mode, s.model);
  $("#tel-voice").textContent = s.voice ? "ON" : "OFF";
  fillList("#reminders", s.reminders || [], "No engagements pending.", (r) => {
    const li = document.createElement("li"); li.append(r.text); const w = document.createElement("span"); w.className = "when"; w.textContent = relTime(r.due); li.appendChild(w); return li;
  });
  fillList("#memory", (s.memory || []).slice(-6).reverse(), "Nothing committed to memory.", (f) => { const li = document.createElement("li"); li.textContent = f; return li; });
  fillList("#agenda", s.agenda || [], "The agenda is clear.", (task) => {
    const li = document.createElement("li"); li.append(task.task); if (task.overdue) li.className = "overdue";
    const w = document.createElement("span"); w.className = "when"; w.textContent = task.due; li.appendChild(w); return li;
  });
  const rupees = (n) => `₹${Math.round(n || 0).toLocaleString("en-IN")}`;
  if (s.spent_today != null) $("#spent-today").textContent = rupees(s.spent_today);
  if (s.spent_month != null) $("#spent-month").textContent = rupees(s.spent_month);
  const v = s.vitals || {};
  if (v.battery != null) setDial("battery", v.battery, `${Math.round(v.battery)}%${v.charging ? " ⚡" : ""}`); else setDial("battery", 0, "mains");
  if (v.cpu != null) setDial("cpu", v.cpu, `${Math.round(v.cpu)}%`);
  if (v.memory != null) setDial("memory", v.memory, `${Math.round(v.memory)}%`);
  if (s.study && typeof Study !== "undefined") Study.apply(s.study);
  if (s.wellbeing && typeof Wellbeing !== "undefined") Wellbeing.apply(s.wellbeing);
  if (s.call && typeof Calls !== "undefined") Calls.apply(s.call);
}

/* ---------------- Events from Python ---------------- */
let askedAt = 0;
window.Sebas = {
  receive(evt) {
    switch (evt.type) {
      case "state": setState(evt.state); break;
      case "transcript":
        addEntry(evt.role, evt.text);
        if (evt.role === "user") askedAt = performance.now();
        else if (askedAt) { $("#mind-latency").textContent = `${((performance.now() - askedAt) / 1000).toFixed(1)} s`; askedAt = 0; refresh(); }
        break;
      case "tool": toolEvent(evt); break;
      case "mic": live.mic = evt.level; break;
      case "speech": live.envelope = evt.envelope || []; live.envStep = evt.step || 0.04; live.envStart = performance.now(); break;
      case "mode": setMode(evt.mode, evt.model); break;
      case "notice": addEntry("notice", evt.text); break;
      case "gesture": gesture(evt.name); break;
      case "sleep": gesture("bow", 4000); setState("idle"); $("#farewell").classList.add("on"); break;
      case "egg": Eggs.play(evt.name); break;
      case "game": if (typeof Games !== "undefined") Games.show(evt.name); break;  // a top-level const is not on window
      case "wellbeing": if (typeof Wellbeing !== "undefined") Wellbeing.nudge(evt.nudge, evt.line); break;
      case "call": if (typeof Calls !== "undefined") Calls.setState(evt); break;
      case "call_line": if (typeof Calls !== "undefined") Calls.line(evt.who, evt.text); break;
      case "call_ask": if (typeof Calls !== "undefined") Calls.askName(evt.names); break;
      case "call_summary":
        addEntry("notice", `Call summary: ${evt.text}`);
        if (typeof Calls !== "undefined") Calls.summary(evt.text);
        break;
      case "study":
        if (typeof Study === "undefined") break;
        if (evt.view === "pomodoro") Study.setSession(evt.session);
        else if (evt.view === "cards") Study.cards(evt.subject);
        else if (evt.view === "quiz") Study.quiz(evt.subject);
        break;
    }
  },
};

/* ---------------- Talking to Python ---------------- */
const api = () => window.pywebview && window.pywebview.api;
async function refresh() {
  // nothing to update on screen while minimised or while a game is open
  if (document.hidden || document.body.classList.contains("gaming")) return;
  const a = api(); if (a) { try { applySnapshot(await a.snapshot()); } catch {} }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
function send(text) {
  text = (text || "").trim(); if (!text) return;
  Sound.tick();
  if (api()) api().send_text(text); else Demo.reply(text);
}
function wireControls() {
  $("#bell-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#ask").value); $("#ask").value = ""; });
  document.querySelectorAll(".quick button[data-ask]").forEach((b) => b.addEventListener("click", () => send(b.dataset.ask)));
  $("#bell").addEventListener("click", async () => {
    const bell = $("#bell"); bell.classList.remove("ring"); void bell.offsetWidth; bell.classList.add("ring"); Sound.bell();
    if (api()) await api().push_to_talk(); else setState("listening");
  });
  $("#btn-min").addEventListener("click", () => api() && api().minimize());
  $("#btn-close").addEventListener("click", () => (api() ? api().close() : window.close()));
  const sb = $("#btn-sound"), ab = $("#btn-ambient");
  const paint = () => { sb.classList.toggle("off", !Sound.on); ab.classList.toggle("off", document.body.dataset.ambient === "off"); };
  sb.addEventListener("click", () => { Sound.on = !Sound.on; prefs.sound = Sound.on; savePrefs(); paint(); Sound.tick(); });
  ab.addEventListener("click", () => { const off = document.body.dataset.ambient !== "off"; document.body.dataset.ambient = off ? "off" : "on"; prefs.ambient = !off; savePrefs(); paint(); });
  if (prefs.ambient === false) document.body.dataset.ambient = "off";
  paint();
  addEventListener("keydown", (e) => { if (e.key === "Escape") $("#ask").blur(); else if (e.key === "/" && document.activeElement !== $("#ask")) { e.preventDefault(); $("#ask").focus(); } });
  addEventListener("pointerdown", () => Sound.ensure(), { once: true });
}
function startClock() {
  const tick = () => { $("#clock").textContent = fmtTime(); };
  tick(); setInterval(tick, 10000);
}

/* ---------------- Demo mode (plain browser preview) ---------------- */
const Demo = {
  start(frozen) {
    setMode("cloud"); $("#tel-voice").textContent = "DEMO";
    applySnapshot({ mode: "cloud", voice: true, vitals: { battery: 86, charging: true, cpu: 23, memory: 71 },
      reminders: [{ due: Date.now() / 1000 + 900, text: "Stretch" }, { due: Date.now() / 1000 + 3600, text: "Call the tailor" }],
      memory: ["The user prefers tea over coffee.", "Main project: the portfolio site.", "Prefers metric units."],
      agenda: [{ task: "Submit the DBMS assignment", due: "Fri 13 Nov 05:00 PM" }, { task: "Renew the domain", due: "today", overdue: false }],
      spent_today: 240, spent_month: 6850,
      study: { session: null, focus_today: 50, exams: [{ subject: "DBMS", days: 12 }, { subject: "Operating Systems", days: 3 }],
               decks: [{ subject: "DBMS", cards: 20, due: 6, quiz: 10 }] },
      wellbeing: { water_today: 3, active_minutes: 42 } });
    addEntry("user", "Sebas, how are my deployments?");
    addEntry("sebas", "All three deployments are healthy, sir. The portfolio was published to production four minutes ago.");
    addEntry("notice", "Listening. Say “Sebas, rise”, or ring the bell.");
    toolEvent({ phase: "start", tool: "vercel_deployments" }); toolEvent({ phase: "end", tool: "vercel_deployments", success: true });
    if (frozen === "bow" || frozen === "sleep") { setState("idle"); setTimeout(() => (frozen === "bow" ? gesture("bow", 60000) : window.Sebas.receive({ type: "sleep" })), 100); return; }
    if (frozen && frozen.startsWith("pose-")) { setTimeout(() => setPose(frozen.slice(5), 60000), 100); return; }
    if (frozen) { setState(frozen); if (frozen === "speaking") this.fakeSpeech(true); if (frozen === "listening") setInterval(() => { live.mic = 0.3 + Math.random() * 0.6; }, 120); return; }
    setInterval(() => { live.mic = live.state === "listening" ? 0.2 + Math.random() * 0.7 : Math.random() * 0.05; }, 150);
  },
  fakeSpeech(loop) {
    live.envelope = Array.from({ length: 400 }, (_, i) => Math.max(0, Math.abs(Math.sin(i * 0.7)) * (0.5 + Math.random() * 0.5) - (i % 23 < 3 ? 1 : 0)));
    live.envStart = performance.now(); live.envStep = 0.04; if (loop) setInterval(() => (live.envStart = performance.now()), 15000);
  },
  reply(text) {
    addEntry("user", text); setState("thinking");
    toolEvent({ phase: "start", tool: "system_status" });
    setTimeout(() => {
      toolEvent({ phase: "end", tool: "system_status", success: true });
      addEntry("sebas", "This is a preview, sir. Launched through run.bat, I shall answer in earnest."); setState("speaking"); this.fakeSpeech();
      setTimeout(() => setState("idle"), 4200);
    }, 1600);
  },
};

/* ---------------- Anime Easter eggs ---------------- */
const Eggs = {
  timer: 0,
  flash(name, ms) {
    document.body.dataset.egg = name; clearTimeout(this.timer);
    this.timer = setTimeout(() => { if (document.body.dataset.egg === name) delete document.body.dataset.egg; }, ms);
  },
  play(name) {
    if (name === "nazarick-on" || name === "nazarick-off") return this.nazarick(name === "nazarick-on");
    if (name === "divergence") return this.divergence();
    if (name === "power") return this.power();
    if (name === "butler") { this.flash("butler", 4000); gesture("bow", 1300); Sound.tone(110, 1.2, 0.06, "sawtooth"); }
    if (name === "sharingan") { this.flash("sharingan", 5000); Sound.tone(1320, 0.12, 0.04, "square"); Sound.tone(660, 0.4, 0.03, "square", 0.12); }
  },
  nazarick(on) { // Ainz Ooal Gown
    document.body.classList.toggle("nazarick", on);
    $(".brand p").textContent = on ? "Head Butler · Great Tomb of Nazarick" : "Household Intelligence · Est. MMXXVI";
    gesture("bow", 1600);
    [196, 233, 294].forEach((f, i) => Sound.tone(on ? f : f * 2, 1.4, 0.04, "triangle", i * 0.12));
  },
  power() { // It's over 9000!
    this.flash("power", 5200);
    Object.values(dials).forEach((d, i) => setTimeout(() => {
      d.needle.style.transform = "rotate(152deg)"; d.val.textContent = "OVER 9000"; Sound.tone(400 + i * 220, 0.25, 0.05, "square");
    }, i * 260));
    setTimeout(() => applySnapshot(lastSnapshot), 5300);
  },
  divergence() { // El Psy Kongroo
    const box = $("#divergence"), tubes = box.querySelector(".tubes"), target = "1.048596";
    tubes.replaceChildren(...[...target].map((ch) => {
      const d = document.createElement("div"); d.className = "tube" + (ch === "." ? " dot" : ""); d.textContent = ch === "." ? "." : "0"; return d;
    }));
    box.classList.add("on");
    const cells = [...tubes.children];
    const roll = setInterval(() => cells.forEach((c, i) => { if (!c.dataset.done && target[i] !== ".") c.textContent = Math.floor(Math.random() * 10); }), 70);
    cells.forEach((c, i) => setTimeout(() => { c.dataset.done = "1"; c.textContent = target[i]; Sound.tick(); }, 1300 + i * 260));
    setTimeout(() => clearInterval(roll), 1300 + cells.length * 260);
    setTimeout(() => box.classList.remove("on"), 8200);
  },
};
// Konami code: up up down down left right left right B A, toggles Sebas Tian's attire
const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
let konamiAt = 0;
function setCostume(on, quiet) {
  const bust = $("#bust");
  if (on) bust.dataset.costume = "tian"; else delete bust.dataset.costume;
  prefs.costume = on; savePrefs();
  if (quiet) return;
  addEntry("notice", on ? "A change of attire: Sebas Tian, Head Butler of Nazarick." : "The household attire, restored.");
  gesture("bow", 1300); Sound.bell();
}
addEventListener("keydown", (e) => {
  if (document.activeElement === $("#ask")) return;
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  konamiAt = key === KONAMI[konamiAt] ? konamiAt + 1 : key === KONAMI[0] ? 1 : 0;
  if (konamiAt === KONAMI.length) { konamiAt = 0; setCostume($("#bust").dataset.costume !== "tian"); }
});

/* ---------------- Boot ---------------- */
function boot() {
  buildRings(); buildDials(); startDust(); startHalo(); startClock(); wireControls();
  if (prefs.costume || params.get("costume") === "tian") setCostume(true, true);
  if (params.get("egg")) setTimeout(() => Eggs.play(params.get("egg")), 900); // for previews
  const skip = params.has("noboot");
  if (skip) $("#boot").remove(); else setTimeout(() => $("#boot").classList.add("done"), 3000);
  if (!skip) setTimeout(() => Sound.bell(), 1200);
  const connect = async () => { applySnapshot(await api().ready()); setInterval(refresh, 4000); };
  if (api()) connect();
  else {
    let started = false;
    addEventListener("pywebviewready", () => { if (!started) { started = true; connect(); } });
    setTimeout(() => { if (!started && !api()) { started = true; Demo.start(params.get("demo")); } }, 800);
  }
}
boot();

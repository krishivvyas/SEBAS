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
function startDust() {
  const c = $("#dust"), g = c.getContext("2d"); let motes = [];
  const size = () => {
    c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
    motes = Array.from({ length: 70 }, () => ({ x: Math.random() * c.width, y: Math.random() * c.height,
      r: (Math.random() * 1.4 + 0.3) * devicePixelRatio, v: Math.random() * 0.25 + 0.05, p: Math.random() * 6.28, gold: Math.random() < 0.75 }));
  };
  size(); addEventListener("resize", size);
  (function frame(t) {
    if (document.body.dataset.ambient !== "off") {
      g.clearRect(0, 0, c.width, c.height);
      for (const m of motes) {
        m.y -= m.v * devicePixelRatio; m.x += Math.sin(t / 3000 + m.p) * 0.15;
        if (m.y < -5) { m.y = c.height + 5; m.x = Math.random() * c.width; }
        g.globalAlpha = 0.25 + 0.35 * Math.abs(Math.sin(t / 1400 + m.p));
        g.fillStyle = m.gold ? "#e6c77f" : "#7ff0e4"; g.beginPath(); g.arc(m.x, m.y, m.r, 0, 6.283); g.fill();
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
  if (state === "speaking" && butler.el) { pulse("data-nod", 260); setTimeout(() => pulse("data-pat", 220), 420); }
}
function currentAmp(now) {
  if (live.state !== "speaking" || !live.envelope.length) return 0;
  const i = Math.floor((now - live.envStart) / 1000 / live.envStep);
  return i >= 0 && i < live.envelope.length ? live.envelope[i] : 0;
}
/* The butler's snappy frame animation: mouth shapes from the voice envelope,
   random blinks, a nod and a chest pat when he starts speaking. */
const butler = { el: null, frame: -1, nextBlink: 0, blinkUntil: 0, lastSwap: 0 };
function flag(name, on) { if (on) butler.el.setAttribute(name, ""); else butler.el.removeAttribute(name); }
function pulse(name, ms) { flag(name, true); setTimeout(() => flag(name, false), ms); }
function animateButler(now) {
  const b = butler; if (!b.el) b.el = $("#bust");
  if (now - b.lastSwap > 70) { // swap mouth frames at ~14 fps for a hand-drawn feel
    b.lastSwap = now;
    const raw = live.state === "speaking" ? currentAmp(now) : 0;
    const frame = raw < 0.12 ? 0 : raw < 0.4 ? 1 : raw < 0.7 ? 2 : 3;
    if (frame !== b.frame) { b.frame = frame; b.el.dataset.mouth = frame; }
    flag("data-emph", frame === 3);
  }
  if (!b.nextBlink) b.nextBlink = now + 2000;
  if (now > b.nextBlink) { // blink at irregular intervals, sometimes twice
    flag("data-blink", true); b.blinkUntil = now + 110;
    b.nextBlink = now + (Math.random() < 0.2 ? 260 : 2400 + Math.random() * 3600);
  }
  if (b.blinkUntil && now > b.blinkUntil) { flag("data-blink", false); b.blinkUntil = 0; }
}
function startHalo() {
  const c = $("#halo"), g = c.getContext("2d"), bars = 96;
  const size = () => { const r = c.getBoundingClientRect(); c.width = Math.max(1, r.width * devicePixelRatio); c.height = Math.max(1, r.height * devicePixelRatio); };
  size(); new ResizeObserver(size).observe(c.parentElement);
  (function frame(now) {
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
  b.textContent = mode === "local" ? `Local · ${(model || "").replace(":latest", "")}` : mode === "cloud" ? "Claude" : "Waking";
  $("#mind-engine").textContent = mode === "local" ? `${model} (offline)` : mode === "cloud" ? "Claude Opus 5.5" : "—";
  $("#tel-mind").textContent = mode === "local" ? "LOCAL" : mode === "cloud" ? "CLOUD" : "—";
}
function relTime(sec) { const m = Math.max(0, Math.round((sec * 1000 - Date.now()) / 60000)); return m < 1 ? "now" : m < 60 ? `in ${m} min` : `in ${Math.floor(m / 60)} h ${m % 60} m`; }
function fillList(id, items, empty, render) {
  const ul = $(id); ul.replaceChildren();
  if (!items.length) { const li = document.createElement("li"); li.className = "empty"; li.textContent = empty; ul.appendChild(li); return; }
  items.forEach((it) => ul.appendChild(render(it)));
}
function applySnapshot(s) {
  if (!s) return;
  if (s.mode) setMode(s.mode, s.model);
  $("#tel-voice").textContent = s.voice ? "ON" : "OFF";
  fillList("#reminders", s.reminders || [], "No engagements pending.", (r) => {
    const li = document.createElement("li"); li.append(r.text); const w = document.createElement("span"); w.className = "when"; w.textContent = relTime(r.due); li.appendChild(w); return li;
  });
  fillList("#memory", (s.memory || []).slice(-6).reverse(), "Nothing committed to memory.", (f) => { const li = document.createElement("li"); li.textContent = f; return li; });
  const v = s.vitals || {};
  if (v.battery != null) setDial("battery", v.battery, `${Math.round(v.battery)}%${v.charging ? " ⚡" : ""}`); else setDial("battery", 0, "mains");
  if (v.cpu != null) setDial("cpu", v.cpu, `${Math.round(v.cpu)}%`);
  if (v.memory != null) setDial("memory", v.memory, `${Math.round(v.memory)}%`);
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
    }
  },
};

/* ---------------- Talking to Python ---------------- */
const api = () => window.pywebview && window.pywebview.api;
async function refresh() { const a = api(); if (a) { try { applySnapshot(await a.snapshot()); } catch {} } }
function send(text) {
  text = (text || "").trim(); if (!text) return;
  Sound.tick();
  if (api()) api().send_text(text); else Demo.reply(text);
}
function wireControls() {
  $("#bell-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#ask").value); $("#ask").value = ""; });
  document.querySelectorAll(".quick button").forEach((b) => b.addEventListener("click", () => send(b.dataset.ask)));
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
      memory: ["The user prefers tea over coffee.", "Main project: the portfolio site.", "Prefers metric units."] });
    addEntry("user", "Sebas, how are my deployments?");
    addEntry("sebas", "All three deployments are healthy, sir. The portfolio was published to production four minutes ago.");
    addEntry("notice", "Listening. Say “Sebas, rise”, or ring the bell.");
    toolEvent({ phase: "start", tool: "vercel_deployments" }); toolEvent({ phase: "end", tool: "vercel_deployments", success: true });
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

/* ---------------- Boot ---------------- */
function boot() {
  buildRings(); buildDials(); startDust(); startHalo(); startClock(); wireControls();
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

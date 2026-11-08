/* Sebas · Wellbeing nudges on the interface: break and posture, water, and the
   20-20-20 eye cue (a 20-second countdown, never spoken). */
"use strict";

const Wellbeing = (() => {
  const box = $("#nudge");
  const TITLES = { break: "Time for a stretch", water: "A glass of water", eye: "Rest your eyes" };
  const ICONS = { break: "⤒", water: "◍", eye: "◉" };
  let hideTimer = null, countdown = null;
  function hide() { box.classList.remove("on"); clearTimeout(hideTimer); clearInterval(countdown); }
  function nudge(kind, line) {
    hide();
    box.dataset.kind = kind;
    $("#nudge-icon").textContent = ICONS[kind] || "◆";
    $("#nudge-title").textContent = TITLES[kind] || "A word, sir";
    $("#nudge-line").textContent = line;
    $("#nudge-water").style.display = kind === "water" ? "" : "none";
    box.classList.add("on");
    Sound.tick();
    if (kind === "eye") { // a quiet 20-second countdown, then it goes by itself
      let left = 20;
      $("#nudge-title").textContent = `Rest your eyes · ${left}`;
      countdown = setInterval(() => {
        left -= 1; $("#nudge-title").textContent = left > 0 ? `Rest your eyes · ${left}` : "Thank you, sir";
        if (left <= 0) { clearInterval(countdown); hideTimer = setTimeout(hide, 1500); }
      }, 1000);
    } else hideTimer = setTimeout(hide, 90000);
  }
  $("#nudge-ok").addEventListener("click", hide);
  $("#nudge-water").addEventListener("click", async () => {
    const a = window.pywebview && window.pywebview.api;
    const n = a ? await a.log_water() : Number($("#well-water").textContent) + 1;
    $("#well-water").textContent = n; hide();
  });
  function apply(w) {
    $("#well-water").textContent = `${w.water_today || 0}`;
    $("#well-active").textContent = `${w.active_minutes || 0} min`;
  }
  return { nudge, apply };
})();

if (params.get("nudge")) setTimeout(() => Wellbeing.nudge(params.get("nudge"), params.get("nudge") === "eye"
  ? "Look at something about twenty feet away for twenty seconds, sir. Your eyes will thank you."
  : params.get("nudge") === "water" ? "A glass of water, sir? Hydration is the foundation of every training arc."
  : "Sir, you have been at it for 64 minutes. Might I suggest standing and stretching for a moment?"), 1200);

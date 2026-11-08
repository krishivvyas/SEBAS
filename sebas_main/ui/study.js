/* Sebas · Study mode in the interface.
   - The Pomodoro ring on the stage (counts down here; Python keeps the real timer).
   - Flashcard review and quizzes, shown in the Games Room overlay, from the study
     sets saved by make_study_set: no AI while you study, no quota.
   - Exams, focus time and study sets in the Household panel. */
"use strict";

const Study = (() => {
  const el = Games.el, say = Games.say;
  const pyApi = () => window.pywebview && window.pywebview.api;

  /* ------------------------------------------------ Pomodoro ring */
  let session = null, timer = null;
  const pomo = $("#pomo"), ring = $("#pomo-ring"), CIRC = 2 * Math.PI * 26;
  ring.style.strokeDasharray = CIRC;
  function setSession(s) {
    s = s && s.ends ? s : null;
    if (s && session && s.ends === session.ends && s.phase === session.phase) return; // the 4 s refresh: unchanged
    session = s;
    pomo.classList.toggle("on", !!session);
    document.body.dataset.focus = session ? session.phase : "";
    clearInterval(timer); timer = null;
    if (session) { tick(); timer = setInterval(tick, 1000); } // only while a session runs
  }
  function tick() {
    if (!session) return;
    const left = Math.max(0, session.ends - Date.now() / 1000);
    const total = (session.phase === "focus" ? session.focus : session.rest) * 60;
    $("#pomo-time").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(Math.floor(left % 60)).padStart(2, "0")}`;
    $("#pomo-label").textContent = session.phase === "focus" ? `Focus · ${session.subject}` : "Break";
    $("#pomo-round").textContent = `Round ${session.cycle} of ${session.cycles}`;
    ring.style.strokeDashoffset = CIRC * (1 - left / Math.max(total, 1));
  }
  $("#pomo-stop").addEventListener("click", () => { const a = pyApi(); if (a) a.study_stop(); else setSession(null); });

  /* ------------------------------------------------ flashcards */
  async function cards(subject, demo) {
    const deck = demo || (await pyApi().study_deck(subject));
    Games.open(`Flashcards · ${deck.subject}`, (box) => {
      let i = 0, right = 0;
      const status = el("div", "game-status"), card = el("div", "fc-card"), controls = el("div", "game-controls");
      const q = el("div", "fc-q"), a = el("div", "fc-a");
      card.append(q, a);
      function show() {
        if (i >= deck.cards.length) {
          status.textContent = "Review complete.";
          q.textContent = `${right} of ${deck.cards.length} remembered.`; a.textContent = deck.extra ? "" : "The rest will return when they are due.";
          card.classList.add("flipped"); controls.replaceChildren(closeBtn());
          say(right === deck.cards.length ? "Every card remembered, sir. Your memory rivals Light Yagami's." :
              "Review complete, sir. The cards you missed will return shortly; repetition is the mother of skill.", true);
          return;
        }
        const c = deck.cards[i];
        status.textContent = `Card ${i + 1} of ${deck.cards.length}${deck.extra ? " · extra practice" : ""}`;
        q.textContent = c.q; a.textContent = c.a; card.classList.remove("flipped");
        const flip = el("button", "game-btn big", "Show answer");
        flip.onclick = () => { card.classList.add("flipped"); Sound.tick(); grades(c); };
        card.onclick = () => { if (!card.classList.contains("flipped")) flip.onclick(); };
        controls.replaceChildren(flip);
      }
      function grades(c) {
        const g = (label, verdict, cls) => { const b = el("button", "game-btn big " + cls, label); b.onclick = () => {
          if (pyApi() && !deck.extra) pyApi().study_grade(deck.subject, c.id, verdict);
          if (verdict !== "again") right++;
          i++; show(); }; return b; };
        controls.replaceChildren(g("Again", "again", "again"), g("Good", "good", "good"), g("Easy", "easy", "easy"));
      }
      const closeBtn = () => { const b = el("button", "game-btn", "Done"); b.onclick = () => Games.close(); return b; };
      box.append(status, card, controls);
      if (!deck.cards.length) { status.textContent = "No cards in this set."; return; }
      say(deck.extra ? "Nothing is due, sir, but a little extra practice never hurt anyone." :
          `${deck.cards.length} cards due, sir. Let us begin. Believe it.`, true);
      show();
    });
  }

  /* ------------------------------------------------ quiz */
  async function quiz(subject, demo) {
    const set = demo || (await pyApi().study_quiz(subject));
    Games.open(`Quiz · ${set.subject}`, (box) => {
      let round = 0, score = 0, answered = false;
      const status = el("div", "game-status"), q = el("div", "trv-q"), opts = el("div", "trv-opts"), controls = el("div", "game-controls");
      const list = set.questions;
      function ask() {
        if (round === list.length) {
          q.textContent = `You scored ${score} of ${list.length}.` + (set.best ? ` (Best before: ${set.best}.)` : "");
          opts.replaceChildren();
          const pct = score / Math.max(list.length, 1);
          say(pct === 1 ? "Full marks, sir! The examiners will weep." : pct >= 0.7 ? "A strong result, sir. The exam holds no fear for you." :
              "A useful rehearsal, sir. Shall we review the flashcards? Every hero has a training arc.", true);
          if (pyApi()) pyApi().study_quiz_done(set.subject, score, list.length);
          return;
        }
        const [text, right, wrong] = list[round]; answered = false;
        status.textContent = `Question ${round + 1} of ${list.length} · score ${score}`; q.textContent = text;
        opts.replaceChildren(...[right, ...wrong].sort(() => Math.random() - 0.5).map((choice) => {
          const b = el("button", "game-btn trv-opt", choice);
          b.onclick = () => {
            if (answered) return; answered = true;
            const ok = choice === right; if (ok) score++;
            [...opts.children].forEach((c) => c.classList.add(c.textContent === right ? "right" : c === b ? "wrong" : "muted"));
            say(ok ? "trv_right" : "trv_wrong", true); Sound.tick();
            setTimeout(() => { round++; ask(); }, 2400);
          };
          return b;
        }));
      }
      const again = el("button", "game-btn", "Retake"); again.onclick = () => quiz(set.subject, demo);
      controls.append(again); box.append(status, q, opts, controls);
      if (!list.length) { status.textContent = "This set has no quiz questions."; return; }
      say(`A quiz on ${set.subject}, sir. ${list.length} questions. I shall be grading strictly.`, true);
      ask();
    });
  }

  /* ------------------------------------------------ household panel */
  function apply(s) {
    if (!s) return;
    setSession(s.session);
    const ul = $("#study"); ul.replaceChildren();
    const row = (text, when, cls) => { const li = el("li", cls || ""); li.append(text); if (when != null) li.append(el("span", "when", when)); ul.append(li); return li; };
    for (const e of s.exams || []) row(`${e.subject} exam`, e.days === 0 ? "today" : e.days === 1 ? "tomorrow" : `in ${e.days} d`, e.days <= 3 ? "overdue" : "");
    for (const d of s.decks || []) {
      const li = row(d.subject, null, "deck");
      const r = el("button", "mini", d.due ? `${d.due} due` : "cards"); r.onclick = () => cards(d.subject);
      const qz = el("button", "mini", "quiz"); qz.onclick = () => quiz(d.subject);
      li.append(el("span", "when"), r); if (d.quiz) li.append(qz);
    }
    if (!ul.children.length) ul.append(el("li", "empty", "No exams or study sets yet."));
    $("#focus-today").textContent = s.focus_today ? `${s.focus_today} min focused today` : "";
  }

  return { setSession, cards, quiz, apply };
})();

if (params.get("study") === "cards") setTimeout(() => Study.cards("", { subject: "DBMS", extra: false, cards: [
  { id: "1", q: "What does ACID stand for?", a: "Atomicity, Consistency, Isolation, Durability." },
  { id: "2", q: "What is a foreign key?", a: "A column that refers to the primary key of another table." }] }), 900);
if (params.get("study") === "quiz") setTimeout(() => Study.quiz("", { subject: "DBMS", best: "7/10", questions: [
  ["Which normal form removes partial dependencies?", "2NF", ["1NF", "3NF", "BCNF"]]] }), 900);
if (params.get("study") === "pomo") setTimeout(() => Study.setSession({ subject: "DBMS", phase: "focus", ends: Date.now() / 1000 + 1122, cycle: 2, cycles: 4, focus: 25, rest: 5 }), 1500);

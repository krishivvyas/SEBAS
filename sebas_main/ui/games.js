/* Sebas · The Games Room.
   Hard-coded games, no AI and no Gemini quota: tic-tac-toe, pong, rock-paper-scissors,
   memory match and anime trivia. Sebas's lines are scripted for each situation and
   spoken through his own voice (window.pywebview.api.say) when the interface runs
   inside Sebas; in a plain browser they appear in his speech bubble only.
   Each game returns a cleanup function, so nothing keeps running once it is closed. */
"use strict";

const Games = (() => {
  const LINES = {
    menu: ["The Games Room is open, sir. What shall it be?", "A little recreation, sir? Even the guardians of Nazarick need their leisure."],
    ttt_start: ["A game of noughts and crosses, sir? Very well. You may have the first move.",
      "Three in a row. Simple rules; the strategy, less so. After you, sir.",
      "As Lelouch would say, every move is part of the plan. Your move, sir."],
    ttt_win: ["All according to keikaku, sir. Keikaku means plan.",
      "Victory. As L would say, I was ninety-nine percent certain.",
      "A butler who lost at noughts and crosses would hardly be worthy of Nazarick."],
    ttt_lose: ["Splendid, sir! Even Ainz-sama would applaud that move.",
      "You have bested me. I shall reflect upon it in the garden.",
      "Well played. Truly, you are the protagonist of this arc."],
    ttt_draw: ["A draw. Like Goku and Vegeta, we appear evenly matched.", "Stalemate, sir. Shall we settle it with a rematch?"],
    pong_start: ["Table tennis, sir? I warn you, my reflexes were honed in the Great Tomb.",
      "Pong. Prepare yourself, sir; this is my Haikyuu arc.", "First to five. I shall not go easy on you... much."],
    pong_you: ["Your point, sir. A spike worthy of Hinata.", "Well struck! I did not see that coming.", "A fine shot. Kageyama would approve."],
    pong_me: ["My point. Za Warudo; I simply stopped time.", "Point to the butler. Plus Ultra!", "Ora. That one was mine, sir."],
    pong_win: ["Game to the butler. Your table tennis has potential, sir; Karasuno would take you.", "I win. Do not be disheartened; even All Might lost once."],
    pong_lose: ["You win, sir! A performance worthy of the national tournament.", "Defeated! I shall return stronger, like Gon after Greed Island."],
    rps_start: ["Rock, paper, scissors, sir? Gon would choose rock. I shall not say what I choose.",
      "First to three. Jan, ken...", "A game of pure chance, sir. Or is it? All according to keikaku."],
    rps_you: ["Your round, sir.", "Hmm. You read me like a Death Note.", "Well chosen."],
    rps_me: ["My round, sir.", "As expected of a butler.", "I foresaw that, as Okabe foresees worldlines."],
    rps_tie: ["A tie. Great minds, sir.", "Again! Jan, ken..."],
    rps_win: ["The match is mine. Jajanken would be prouder of you than you think, sir.", "Victory to the butler. A rematch, perhaps?"],
    rps_lose: ["The match is yours, sir! Splendidly played.", "You win. I yield, as gracefully as a butler may."],
    mem_start: ["A test of memory, sir. I remember every guest of Nazarick by name.",
      "Find the pairs. Take your time; even Frieren needs a few centuries now and then."],
    mem_pair: ["A pair! Splendid.", "Matched, as surely as Okabe finds his worldline.", "Well remembered, sir."],
    mem_done: ["All pairs found, sir! A memory worthy of a Nazarick archivist.", "Complete! Your memory would impress even Sebastian Michaelis."],
    trv_start: ["Anime trivia, sir. Let us see whether you are a true otaku.", "Ten questions. I shall be grading strictly, as befits a butler."],
    trv_right: ["Correct! Ten points to the Survey Corps.", "Precisely, sir. Your otaku credentials are in order.", "Right you are. Plus Ultra!"],
    trv_wrong: ["Alas, no. Even Ainz-sama consults his notes now and then.", "Not quite, sir. A minor setback in the training arc.", "Incorrect. Fear not; every hero has a filler episode."],
    trv_great: ["A perfect score, sir! You are a true otaku. Nazarick salutes you.", "Magnificent! You know your anime as I know the silverware."],
    trv_good: ["A fine showing, sir. Your power level is considerable.", "Very respectable. Another season of watching and you shall be unstoppable."],
    trv_poor: ["A modest score, sir. Might I suggest a few classics this weekend?", "Every protagonist starts somewhere, sir. Your training arc begins today."],
    c4_start: ["Connect Four, sir. Four in a row, and gravity is on nobody's side.", "A game of patience and foresight, sir. Shogi players would feel at home.",
      "Connect Four. I see seven moves ahead; Lelouch saw more, but he had a Geass."],
    c4_block: ["I think not, sir. That column is spoken for.", "A fine trap, sir, but I have read this chapter.", "Blocked. As expected of a butler."],
    c4_win: ["Four in a row. Checkmate, as Lelouch would say, though it is the wrong game.", "Victory, sir. The board was mine from the third move.",
      "I win. Do not be discouraged; even Shikamaru loses to his father."],
    c4_lose: ["Four in a row! Splendid, sir. Shikamaru himself would yawn in admiration.", "You have bested me. I shall study the replay like a shogi master."],
    c4_draw: ["The board is full, sir. A stalemate worthy of Light and L."],
    hm_start: ["Anime hangman, sir. Guess the title or character, one letter at a time.", "A word from the archives of anime, sir. Mind the lantern."],
    hm_good: ["Good letter, sir.", "Precisely.", "Well deduced, sir; Detective Conan would approve."],
    hm_bad: ["Not that one, sir. The lantern dims.", "Alas, no.", "A miss, sir. Even Tanjiro needs a second sniff."],
    hm_hint: ["A hint, sir, before the lantern goes out entirely."],
    hm_win: ["Solved! Your otaku credentials are in impeccable order, sir.", "Correct, sir. You read that like a Death Note."],
    hm_lose: ["The lantern is out, sir. A noble effort; the answer was {word}."],
    snake_start: ["Snake, sir. Arrow keys or W A S D. Do try not to bite yourself; Orochimaru never quite managed it.",
      "Snake. Eat, grow, and avoid the walls, sir. A metaphor for university, perhaps."],
    snake_record: ["A new record, sir! Plus Ultra!", "A new high score. Orochimaru would be envious, sir."],
    snake_over: ["Game over, sir. A respectable length.", "The snake has met its end, sir. Shall we go again?"],
  };

  // a key from LINES, or a ready-made line (the study panels bring their own)
  const pick = (key) => { const a = LINES[key] || [key]; return a[Math.floor(Math.random() * a.length)]; };
  let lastSaid = 0;
  function say(key, force, fill) {
    const line = pick(key).replace(/\{(\w+)\}/g, (m, k) => (fill && fill[k] != null ? fill[k] : m)), now = performance.now();
    $("#game-bubble").textContent = line;
    if (!force && now - lastSaid < 2500) return; // don't talk over himself in fast games
    lastSaid = now;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.say) a.say(line);
  }

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  /* ------------------------------------------------ tic-tac-toe */
  function tictactoe(box) {
    const LINES3 = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
    let board, over, mode = "butler";
    const status = el("div", "game-status"), grid = el("div", "ttt"), controls = el("div", "game-controls");
    const winner = (b) => { for (const [a, c, d] of LINES3) if (b[a] && b[a] === b[c] && b[a] === b[d]) return b[a]; return b.every(Boolean) ? "draw" : null; };
    function minimax(b, player) {
      const w = winner(b);
      if (w === "O") return { score: 1 }; if (w === "X") return { score: -1 }; if (w === "draw") return { score: 0 };
      let best = { score: player === "O" ? -2 : 2 };
      b.forEach((v, i) => {
        if (v) return; b[i] = player; const r = minimax(b, player === "O" ? "X" : "O"); b[i] = null;
        if ((player === "O" && r.score > best.score) || (player === "X" && r.score < best.score)) best = { score: r.score, move: i };
      });
      return best;
    }
    function sebasMove() {
      const free = board.map((v, i) => (v ? null : i)).filter((i) => i !== null);
      const blunder = mode === "butler" && Math.random() < 0.3;
      const move = blunder ? free[Math.floor(Math.random() * free.length)] : minimax(board, "O").move;
      board[move] = "O"; Sound.tick(); render(); finish();
    }
    function finish() {
      const w = winner(board); if (!w) return false;
      over = true;
      status.textContent = w === "draw" ? "A draw." : w === "X" ? "You win!" : "Sebas wins.";
      say(w === "draw" ? "ttt_draw" : w === "X" ? "ttt_lose" : "ttt_win", true);
      return true;
    }
    function render() {
      grid.replaceChildren(...board.map((v, i) => {
        const c = el("button", "ttt-cell" + (v ? " " + v : ""), v ? (v === "X" ? "✕" : "◯") : "");
        c.onclick = () => { if (over || board[i]) return; board[i] = "X"; Sound.tick(); render(); if (!finish()) { status.textContent = "Sebas is considering…"; setTimeout(() => { sebasMove(); if (!over) status.textContent = "Your move, sir."; }, 450); } };
        return c;
      }));
    }
    function start() { board = Array(9).fill(null); over = false; status.textContent = "Your move, sir. You are ✕."; render(); say("ttt_start", true); }
    const level = el("button", "game-btn", "Difficulty: Butler");
    level.onclick = () => { mode = mode === "butler" ? "nazarick" : "butler"; level.textContent = `Difficulty: ${mode === "butler" ? "Butler" : "Nazarick (perfect)"}`; start(); };
    const again = el("button", "game-btn", "New game"); again.onclick = start;
    controls.append(level, again); box.append(status, grid, controls); start();
    return () => {};
  }

  /* ------------------------------------------------ pong */
  function pong(box) {
    const W = 640, H = 380, canvas = el("canvas", "pong"), status = el("div", "game-status", "Mouse or ↑ ↓ to move · first to 5");
    canvas.width = W; canvas.height = H; box.append(status, canvas);
    const g = canvas.getContext("2d");
    const s = { you: H / 2, me: H / 2, bx: W / 2, by: H / 2, vx: 4, vy: 2.4, ys: 0, ms: 0, keys: {}, run: true, pause: 900 };
    const PAD = 70, PW = 10;
    const move = (e) => { const r = canvas.getBoundingClientRect(); s.you = ((e.clientY - r.top) / r.height) * H; };
    const kd = (e) => { s.keys[e.key] = true; if (e.key.startsWith("Arrow")) e.preventDefault(); }, ku = (e) => { s.keys[e.key] = false; };
    canvas.addEventListener("mousemove", move); addEventListener("keydown", kd); addEventListener("keyup", ku);
    function serve(dir) { s.bx = W / 2; s.by = H / 2; s.vx = 4.2 * dir; s.vy = (Math.random() * 2 - 1) * 3; s.pause = 700; }
    function point(you) {
      if (you) s.ys++; else s.ms++;
      if (s.ys === 5 || s.ms === 5) { s.run = false; say(s.ys === 5 ? "pong_lose" : "pong_win", true); status.textContent = s.ys === 5 ? "You win! Click to play again." : "Sebas wins. Click to play again."; return; }
      say(you ? "pong_you" : "pong_me"); serve(you ? 1 : -1);
    }
    canvas.addEventListener("click", () => { if (!s.run) { s.ys = s.ms = 0; s.run = true; serve(1); status.textContent = "First to 5."; say("pong_start", true); loop(); } });
    let last = performance.now(), raf;
    function loop(now = performance.now()) {
      const dt = Math.min((now - last) / 16.7, 3); last = now;
      if (s.keys.ArrowUp) s.you -= 7 * dt; if (s.keys.ArrowDown) s.you += 7 * dt;
      s.you = Math.max(PAD / 2, Math.min(H - PAD / 2, s.you));
      if (s.pause > 0) s.pause -= 16.7 * dt;
      else {
        s.bx += s.vx * dt; s.by += s.vy * dt;
        if (s.by < 6 || s.by > H - 6) { s.vy *= -1; s.by = Math.max(6, Math.min(H - 6, s.by)); }
        // Sebas's paddle follows the ball, with a top speed: skilled, not perfect
        const target = s.vx > 0 ? s.by : H / 2, step = Math.max(-4.6, Math.min(4.6, target - s.me));
        s.me += step * dt;
        const hit = (py, x) => Math.abs(s.by - py) < PAD / 2 + 6 && Math.abs(s.bx - x) < PW;
        if (s.vx < 0 && hit(s.you, 24)) { s.vx = Math.min(-s.vx * 1.06, 11); s.vy += (s.by - s.you) * 0.08; Sound.tick(); }
        if (s.vx > 0 && hit(s.me, W - 24)) { s.vx = -Math.min(s.vx * 1.06, 11); s.vy += (s.by - s.me) * 0.08; Sound.tick(); }
        if (s.bx < 0) point(false); else if (s.bx > W) point(true);
      }
      g.fillStyle = "#070b16"; g.fillRect(0, 0, W, H);
      g.strokeStyle = "rgba(201,164,92,.35)"; g.setLineDash([6, 10]); g.beginPath(); g.moveTo(W / 2, 0); g.lineTo(W / 2, H); g.stroke(); g.setLineDash([]);
      g.fillStyle = "#5fe3d6"; g.fillRect(14, s.you - PAD / 2, PW, PAD);
      g.fillStyle = "#f1d892"; g.fillRect(W - 24, s.me - PAD / 2, PW, PAD);
      g.beginPath(); g.arc(s.bx, s.by, 6, 0, 6.283); g.fillStyle = "#efe6d2"; g.fill();
      g.font = "600 34px Cinzel, serif"; g.textAlign = "center";
      g.fillStyle = "#5fe3d6"; g.fillText(s.ys, W / 2 - 60, 46); g.fillStyle = "#f1d892"; g.fillText(s.ms, W / 2 + 60, 46);
      g.font = "11px Mono, monospace"; g.fillStyle = "rgba(239,230,210,.5)"; g.fillText("YOU", W / 2 - 60, 64); g.fillText("SEBAS", W / 2 + 60, 64);
      if (s.run) raf = requestAnimationFrame(loop);
    }
    serve(1); say("pong_start", true); loop();
    return () => { s.run = false; cancelAnimationFrame(raf); removeEventListener("keydown", kd); removeEventListener("keyup", ku); };
  }

  /* ------------------------------------------------ rock-paper-scissors */
  function rps(box) {
    const MOVES = { rock: "✊", paper: "✋", scissors: "✌" }, BEATS = { rock: "scissors", paper: "rock", scissors: "paper" };
    let you = 0, me = 0, done = false;
    const status = el("div", "game-status"), arena = el("div", "rps-arena"), choices = el("div", "game-controls");
    function play(choice) {
      if (done) return;
      const mine = Object.keys(MOVES)[Math.floor(Math.random() * 3)];
      arena.replaceChildren(el("div", "rps-hand you", MOVES[choice]), el("div", "rps-vs", "vs"), el("div", "rps-hand me", MOVES[mine]));
      if (choice === mine) { say("rps_tie"); }
      else if (BEATS[choice] === mine) { you++; say("rps_you"); } else { me++; say("rps_me"); }
      status.textContent = `You ${you} · ${me} Sebas`;
      if (you === 3 || me === 3) { done = true; status.textContent += you === 3 ? " · You win the match!" : " · Sebas wins the match."; say(you === 3 ? "rps_lose" : "rps_win", true); }
    }
    for (const m of Object.keys(MOVES)) { const b = el("button", "game-btn big", `${MOVES[m]} ${m}`); b.onclick = () => play(m); choices.append(b); }
    const again = el("button", "game-btn", "New match"); again.onclick = () => { you = me = 0; done = false; arena.replaceChildren(); status.textContent = "First to three."; say("rps_start", true); };
    choices.append(again); status.textContent = "First to three."; box.append(status, arena, choices); say("rps_start", true);
    return () => {};
  }

  /* ------------------------------------------------ memory match */
  function memory(box) {
    const SYMBOLS = ["☯", "⚔", "✦", "☾", "♛", "⚙", "❖", "♞"];
    let deck, open, found, moves, locked;
    const status = el("div", "game-status"), grid = el("div", "mem"), controls = el("div", "game-controls");
    function start() {
      deck = [...SYMBOLS, ...SYMBOLS].sort(() => Math.random() - 0.5); open = []; found = new Set(); moves = 0; locked = false;
      render(); status.textContent = "Find the eight pairs."; say("mem_start", true);
    }
    function render() {
      grid.replaceChildren(...deck.map((sym, i) => {
        const shown = found.has(sym) || open.includes(i);
        const c = el("button", "mem-card" + (shown ? " up" : "") + (found.has(sym) ? " done" : ""), shown ? sym : "S");
        c.onclick = () => flip(i); return c;
      }));
    }
    function flip(i) {
      if (locked || open.includes(i) || found.has(deck[i])) return;
      open.push(i); Sound.tick(); render();
      if (open.length < 2) return;
      moves++; const [a, b] = open;
      if (deck[a] === deck[b]) {
        found.add(deck[a]); open = []; render();
        if (found.size === SYMBOLS.length) { status.textContent = `All pairs in ${moves} moves!`; say("mem_done", true); }
        else { status.textContent = `${found.size} of 8 pairs · ${moves} moves`; say("mem_pair"); }
      } else { locked = true; setTimeout(() => { open = []; locked = false; render(); }, 750); status.textContent = `${found.size} of 8 pairs · ${moves} moves`; }
    }
    const again = el("button", "game-btn", "Shuffle again"); again.onclick = start;
    controls.append(again); box.append(status, grid, controls); start();
    return () => {};
  }

  /* ------------------------------------------------ anime trivia */
  const QUESTIONS = [
    ["Who is the Head Butler of the Great Tomb of Nazarick in Overlord?", "Sebas Tian", ["Demiurge", "Cocytus", "Pandora's Actor"]],
    ["Before he took the name Ainz Ooal Gown, what was the Overlord's in-game name?", "Momonga", ["Momon", "Touch Me", "Ulbert"]],
    ["What name does Light Yagami's alter ego go by in Death Note?", "Kira", ["L", "Near", "Ryuk"]],
    ["What is Lab Member 001's name in Steins;Gate?", "Rintaro Okabe", ["Itaru Hashida", "Kurisu Makise", "Mayuri Shiina"]],
    ["What is the divergence of the Steins Gate worldline?", "1.048596", ["0.571024", "1.130205", "0.337187"]],
    ["What fruit gave Luffy his powers in One Piece?", "Gum-Gum Fruit", ["Flame-Flame Fruit", "Chop-Chop Fruit", "Smoke-Smoke Fruit"]],
    ["What is the name of the Nine-Tailed Fox in Naruto?", "Kurama", ["Shukaku", "Gyuki", "Matatabi"]],
    ["What does Sebastian Michaelis call himself in Black Butler?", "One hell of a butler", ["A humble servant", "The demon butler", "A loyal hound"]],
    ["Which branch of the military ventures beyond the walls in Attack on Titan?", "Survey Corps", ["Garrison", "Military Police", "Training Corps"]],
    ["In the English dub of Dragon Ball Z, who declares \"It's over 9000!\"?", "Vegeta", ["Goku", "Nappa", "Frieza"]],
    ["What is DIO's Stand called in JoJo's Stardust Crusaders?", "The World", ["Star Platinum", "Killer Queen", "Crazy Diamond"]],
    ["Which studio made Spirited Away?", "Studio Ghibli", ["Kyoto Animation", "Madhouse", "Bones"]],
    ["What does Alphonse Elric's soul inhabit in Fullmetal Alchemist?", "A suit of armour", ["A doll", "A cat", "A philosopher's stone"]],
    ["What is Tanjiro's sister called in Demon Slayer?", "Nezuko", ["Kanao", "Shinobu", "Mitsuri"]],
    ["What is All Might's Quirk called in My Hero Academia?", "One For All", ["All For One", "Half-Cold Half-Hot", "Explosion"]],
    ["Which Zoldyck is Gon's best friend in Hunter x Hunter?", "Killua", ["Illumi", "Alluka", "Milluki"]],
    ["What is Lelouch's power to command others called in Code Geass?", "Geass", ["Nen", "Haki", "Stand"]],
    ["What race is Frieren?", "Elf", ["Dwarf", "Demon", "Human"]],
    ["What can Anya do in Spy x Family?", "Read minds", ["See the future", "Turn invisible", "Stop time"]],
    ["What is Saitama's hero name in One Punch Man?", "Caped Baldy", ["Silver Fang", "Genos", "King"]],
    ["Who is Yuji Itadori's blindfolded teacher in Jujutsu Kaisen?", "Satoru Gojo", ["Kento Nanami", "Suguru Geto", "Masamichi Yaga"]],
    ["What is Kirito's real name in Sword Art Online?", "Kazuto Kirigaya", ["Kazuma Satou", "Kyouya Hibari", "Kotaro Yamada"]],
    ["Which Evangelion unit does Shinji Ikari pilot?", "Unit-01", ["Unit-00", "Unit-02", "Unit-13"]],
    ["What is the spaceship called in Cowboy Bebop?", "Bebop", ["Swordfish", "Red Tail", "Hammerhead"]],
  ];
  function trivia(box) {
    let round, score, list, answered;
    const status = el("div", "game-status"), q = el("div", "trv-q"), opts = el("div", "trv-opts"), controls = el("div", "game-controls");
    function ask() {
      if (round === list.length) {
        q.textContent = `You scored ${score} of ${list.length}.`; opts.replaceChildren();
        say(score === list.length ? "trv_great" : score >= 6 ? "trv_good" : "trv_poor", true); return;
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
          setTimeout(() => { round++; ask(); }, 2200);
        };
        return b;
      }));
    }
    function start() { list = [...QUESTIONS].sort(() => Math.random() - 0.5).slice(0, 10); round = 0; score = 0; say("trv_start", true); setTimeout(ask, 400); }
    const again = el("button", "game-btn", "New quiz"); again.onclick = start;
    controls.append(again); box.append(status, q, opts, controls); start();
    return () => {};
  }

  /* ------------------------------------------------ connect four */
  function connect4(box) {
    const C = 7, R = 6;
    let board, over, level = "butler", thinking = false;
    const status = el("div", "game-status"), grid = el("div", "c4"), controls = el("div", "game-controls");
    const at = (b, c, r) => b[c * R + r];
    const drop = (b, c, who) => { for (let r = 0; r < R; r++) if (!b[c * R + r]) { b[c * R + r] = who; return r; } return -1; };
    const lift = (b, c) => { for (let r = R - 1; r >= 0; r--) if (b[c * R + r]) { b[c * R + r] = null; return; } };
    const open = (b) => [3, 2, 4, 1, 5, 0, 6].filter((c) => !b[c * R + R - 1]); // centre first: better pruning
    const DIRS = [[1, 0], [0, 1], [1, 1], [1, -1]];
    function winner(b) {
      for (let c = 0; c < C; c++) for (let r = 0; r < R; r++) {
        const w = at(b, c, r); if (!w) continue;
        for (const [dc, dr] of DIRS) {
          let k = 1; while (k < 4) { const cc = c + dc * k, rr = r + dr * k; if (cc < 0 || cc >= C || rr < 0 || rr >= R || at(b, cc, rr) !== w) break; k++; }
          if (k === 4) return w;
        }
      }
      return open(b).length ? null : "draw";
    }
    function score(b) { // windows of four: favour Sebas's (O) open threes, fear yours (X)
      let s = 0;
      for (let r = 0; r < R; r++) if (at(b, 3, r) === "O") s += 3; else if (at(b, 3, r) === "X") s -= 3;
      for (let c = 0; c < C; c++) for (let r = 0; r < R; r++) for (const [dc, dr] of DIRS) {
        const ec = c + dc * 3, er = r + dr * 3; if (ec < 0 || ec >= C || er < 0 || er >= R) continue;
        let o = 0, x = 0; for (let k = 0; k < 4; k++) { const v = at(b, c + dc * k, r + dr * k); if (v === "O") o++; else if (v === "X") x++; }
        if (o && x) continue;
        s += o === 3 ? 5 : o === 2 ? 2 : 0; s -= x === 3 ? 6 : x === 2 ? 2 : 0;
      }
      return s;
    }
    function search(b, depth, alpha, beta, me) {
      const w = winner(b);
      if (w === "O") return 100000 + depth; if (w === "X") return -100000 - depth; if (w === "draw") return 0;
      if (depth === 0) return score(b);
      let best = me ? -Infinity : Infinity;
      for (const c of open(b)) {
        drop(b, c, me ? "O" : "X"); const v = search(b, depth - 1, alpha, beta, !me); lift(b, c);
        if (me) { best = Math.max(best, v); alpha = Math.max(alpha, v); } else { best = Math.min(best, v); beta = Math.min(beta, v); }
        if (beta <= alpha) break;
      }
      return best;
    }
    function choose() {
      const cols = open(board);
      if (level === "butler" && Math.random() < 0.25) return cols[Math.floor(Math.random() * cols.length)];
      const depth = level === "butler" ? 2 : 6;
      let best = cols[0], bestV = -Infinity;
      for (const c of cols) { drop(board, c, "O"); const v = search(board, depth - 1, -Infinity, Infinity, false); lift(board, c); if (v > bestV) { bestV = v; best = c; } }
      return best;
    }
    function youCouldWinAt(c) { const r = drop(board, c, "X"); const w = r >= 0 && winner(board) === "X"; if (r >= 0) lift(board, c); return w; }
    function render(last) {
      grid.replaceChildren();
      for (let c = 0; c < C; c++) {
        const col = el("button", "c4-col"); col.onclick = () => play(c);
        for (let r = R - 1; r >= 0; r--) { const v = at(board, c, r); col.append(el("span", "c4-cell" + (v ? " " + v : "") + (last === c * R + r ? " last" : ""))); }
        grid.append(col);
      }
    }
    function finish() {
      const w = winner(board); if (!w) return false;
      over = true; status.textContent = w === "draw" ? "A draw." : w === "X" ? "You win!" : "Sebas wins.";
      say(w === "draw" ? "c4_draw" : w === "X" ? "c4_lose" : "c4_win", true); return true;
    }
    function play(c) {
      if (over || thinking) return;
      const r = drop(board, c, "X"); if (r < 0) return;
      Sound.tick(); render(c * R + r); if (finish()) return;
      thinking = true; status.textContent = "Sebas is considering…";
      setTimeout(() => {
        const threat = open(board).find(youCouldWinAt);
        const mc = choose(), mr = drop(board, mc, "O");
        if (threat != null && mc === threat) say("c4_block");
        thinking = false; Sound.tick(); render(mc * R + mr);
        if (!finish()) status.textContent = "Your move, sir. You are cyan.";
      }, 60);
    }
    function start() { board = Array(C * R).fill(null); over = false; thinking = false; render(); status.textContent = "Your move, sir. You are cyan; click a column."; say("c4_start", true); }
    const lv = el("button", "game-btn", "Difficulty: Butler");
    lv.onclick = () => { level = level === "butler" ? "nazarick" : "butler"; lv.textContent = `Difficulty: ${level === "butler" ? "Butler" : "Nazarick (strong)"}`; start(); };
    const again = el("button", "game-btn", "New game"); again.onclick = start;
    controls.append(lv, again); box.append(status, grid, controls); start();
    return () => { over = true; };
  }

  /* ------------------------------------------------ anime hangman */
  const HANGMAN = [
    ["NARUTO", "A ninja who wants to be Hokage"], ["ONE PIECE", "The treasure every pirate seeks"], ["DEATH NOTE", "A notebook with deadly rules"],
    ["STEINS GATE", "A worldline, and a microwave"], ["ATTACK ON TITAN", "Walls, and what is beyond them"], ["FULLMETAL ALCHEMIST", "Equivalent exchange"],
    ["DEMON SLAYER", "A boy, his sister, and a breathing style"], ["JUJUTSU KAISEN", "Cursed energy and a blindfolded teacher"],
    ["SPY X FAMILY", "A spy, an assassin and a telepath play house"], ["FRIEREN", "An elf who outlives her party"], ["OVERLORD", "A skeleton lord and his loyal butler"],
    ["COWBOY BEBOP", "Bounty hunters in space, with jazz"], ["HUNTER X HUNTER", "Gon searches for his father"], ["MOB PSYCHO", "A psychic boy at one hundred percent"],
    ["VINLAND SAGA", "Vikings, revenge, and a true warrior"], ["HAIKYUU", "Volleyball, and a boy who flies"], ["CODE GEASS", "A prince with the power of absolute obedience"],
    ["BLACK BUTLER", "One hell of a butler"], ["SAITAMA", "A hero who wins with one punch"], ["LEVI ACKERMAN", "Humanity's strongest soldier"],
    ["KURISU MAKISE", "An assistant, and a genius"], ["SEBAS TIAN", "Head Butler of Nazarick"], ["GOJO SATORU", "The strongest, blindfolded"],
    ["KILLUA", "An assassin's son with lightning"], ["ZORO", "A swordsman who gets lost"], ["TOTORO", "A forest spirit at a bus stop"],
  ];
  function hangman(box) {
    let word, hint, guessed, misses, done;
    const MAX = 6;
    const status = el("div", "game-status"), lantern = el("div", "hm-lantern"), shown = el("div", "hm-word"), hintEl = el("div", "hm-hint");
    const keys = el("div", "hm-keys"), controls = el("div", "game-controls");
    // the lantern: each miss removes a lit part (no gallows in this household)
    lantern.innerHTML = `<svg viewBox="0 0 120 150"><line x1="60" y1="2" x2="60" y2="22" class="hm-p" data-n="6"/><rect x="40" y="22" width="40" height="10" rx="2" class="hm-p" data-n="5"/>
      <path d="M36 34 Q60 28 84 34 L80 112 Q60 118 40 112 Z" class="hm-p body" data-n="4"/><path d="M48 50 L48 100 M60 46 L60 106 M72 50 L72 100" class="hm-p ribs" data-n="3"/>
      <ellipse cx="60" cy="76" rx="12" ry="18" class="hm-p flame" data-n="2"/><rect x="44" y="114" width="32" height="8" rx="2" class="hm-p" data-n="1"/></svg>`;
    function render() {
      shown.textContent = [...word].map((ch) => (ch === " " ? "\u2003" : guessed.has(ch) ? ch : "_")).join(" ");
      lantern.querySelectorAll(".hm-p").forEach((part) => part.classList.toggle("out", Number(part.dataset.n) > MAX - misses));
      status.textContent = done ? status.textContent : `${MAX - misses} light${MAX - misses === 1 ? "" : "s"} left`;
      hintEl.textContent = misses >= 3 ? `Hint: ${hint}` : "";
      keys.querySelectorAll("button").forEach((b) => { b.disabled = done || guessed.has(b.textContent); b.classList.toggle("miss", guessed.has(b.textContent) && !word.includes(b.textContent)); });
    }
    function guess(ch) {
      if (done || guessed.has(ch) || !/^[A-Z]$/.test(ch)) return;
      guessed.add(ch); Sound.tick();
      if (word.includes(ch)) { if (Math.random() < 0.35) say("hm_good"); }
      else { misses++; say(misses === 3 ? "hm_hint" : "hm_bad", misses === 3); }
      if ([...word].every((c) => c === " " || guessed.has(c))) { done = true; status.textContent = "Solved!"; say("hm_win", true); }
      else if (misses >= MAX) { done = true; status.textContent = `The answer was ${word}.`; [...word].forEach((c) => guessed.add(c)); say("hm_lose", true, { word }); }
      render();
    }
    for (const ch of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") { const b = el("button", "hm-key", ch); b.onclick = () => guess(ch); keys.append(b); }
    const onKey = (e) => { if (e.key.length === 1) guess(e.key.toUpperCase()); };
    addEventListener("keydown", onKey);
    function start() { [word, hint] = HANGMAN[Math.floor(Math.random() * HANGMAN.length)]; guessed = new Set(); misses = 0; done = false; render(); say("hm_start", true); }
    const again = el("button", "game-btn", "New word"); again.onclick = start;
    controls.append(again);
    const top = el("div", "hm-top"); top.append(lantern, el("div", "hm-right")); top.lastChild.append(shown, hintEl);
    box.append(status, top, keys, controls); start();
    return () => removeEventListener("keydown", onKey);
  }

  /* ------------------------------------------------ snake */
  function snake(box) {
    const N = 20, S = 22, canvas = el("canvas", "snake"), status = el("div", "game-status");
    canvas.width = canvas.height = N * S; box.append(status, canvas);
    const g = canvas.getContext("2d");
    let best = 0; try { best = Number(localStorage.getItem("sebas.snake.best")) || 0; } catch {}
    let body, dir, next, food, score, alive, step, timer, recordSaid, waiting;
    const place = () => { do { food = [Math.floor(Math.random() * N), Math.floor(Math.random() * N)]; } while (body.some(([x, y]) => x === food[0] && y === food[1])); };
    function start() {
      body = [[10, 10], [9, 10], [8, 10]]; dir = [1, 0]; next = [1, 0]; score = 0; alive = true; step = 140; recordSaid = false;
      place(); status.textContent = `Best ${best} · press an arrow key (or WASD) to begin`; say("snake_start", true);
      clearTimeout(timer); waiting = true; draw(); // the snake waits for your first move
    }
    function loop() {
      dir = next;
      const head = [body[0][0] + dir[0], body[0][1] + dir[1]];
      if (head[0] < 0 || head[1] < 0 || head[0] >= N || head[1] >= N || body.some(([x, y]) => x === head[0] && y === head[1])) {
        alive = false; draw();
        if (score > best) { best = score; try { localStorage.setItem("sebas.snake.best", String(best)); } catch {} }
        status.textContent = `Score ${score} · best ${best} · press Space or click to play again`;
        if (!recordSaid) say("snake_over", true);
        return;
      }
      body.unshift(head);
      if (head[0] === food[0] && head[1] === food[1]) {
        score++; Sound.tick(); place(); step = Math.max(60, step - 4);
        if (score > best && best > 0 && !recordSaid) { recordSaid = true; say("snake_record", true); }
        status.textContent = `Score ${score} · best ${Math.max(best, score)}`;
      } else body.pop();
      draw(); timer = setTimeout(loop, step);
    }
    function draw() {
      g.fillStyle = "#070b16"; g.fillRect(0, 0, N * S, N * S);
      g.strokeStyle = "rgba(201,164,92,.07)";
      for (let i = 1; i < N; i++) { g.beginPath(); g.moveTo(i * S, 0); g.lineTo(i * S, N * S); g.moveTo(0, i * S); g.lineTo(N * S, i * S); g.stroke(); }
      g.fillStyle = "#f1d892"; g.beginPath(); g.arc(food[0] * S + S / 2, food[1] * S + S / 2, S / 3, 0, 6.283); g.fill();
      body.forEach(([x, y], i) => { g.fillStyle = i ? `rgba(95,227,214,${Math.max(0.35, 1 - i / body.length)})` : alive ? "#bff7f0" : "#e0705a"; g.fillRect(x * S + 2, y * S + 2, S - 4, S - 4); });
    }
    const KEYS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0], w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] };
    const onKey = (e) => {
      const k = KEYS[e.key] || KEYS[e.key.toLowerCase()];
      if (k) {
        e.preventDefault();
        if (k[0] !== -dir[0] || k[1] !== -dir[1]) next = k;
        if (waiting && alive) { waiting = false; status.textContent = `Score 0 · best ${best}`; loop(); }
      }
      else if (e.key === " " && !alive) { e.preventDefault(); start(); }
    };
    addEventListener("keydown", onKey); canvas.addEventListener("click", () => { if (!alive) start(); });
    start();
    return () => { alive = false; clearTimeout(timer); removeEventListener("keydown", onKey); };
  }

  /* ------------------------------------------------ the room */
  const GAMES = {
    tictactoe: ["Tic-tac-toe", tictactoe], pong: ["Pong", pong], rps: ["Rock · Paper · Scissors", rps],
    memory: ["Memory match", memory], trivia: ["Anime trivia", trivia],
    connect4: ["Connect Four", connect4], hangman: ["Anime hangman", hangman], snake: ["Snake", snake],
  };
  let cleanup = null;
  function stopCurrent() { if (cleanup) { cleanup(); cleanup = null; } }
  function show(name) {
    stopCurrent();
    const room = $("#games"), body = $("#game-body"), title = $("#game-title");
    room.classList.add("on"); document.body.classList.add("gaming"); busy(true); // the stage's animations rest meanwhile
    body.replaceChildren();
    if (!GAMES[name]) {
      title.textContent = "The Games Room";
      const menu = el("div", "game-menu");
      for (const [key, [label]] of Object.entries(GAMES)) { const b = el("button", "game-btn big", label); b.onclick = () => show(key); menu.append(b); }
      body.append(menu); say("menu", true); return;
    }
    title.textContent = GAMES[name][0];
    cleanup = GAMES[name][1](body);
  }
  // Another panel (flashcards, quizzes) in the same room
  function open(label, build) {
    stopCurrent();
    $("#games").classList.add("on"); document.body.classList.add("gaming"); busy(true);
    $("#game-body").replaceChildren(); $("#game-title").textContent = label;
    cleanup = build($("#game-body")) || null;
  }
  function close() { stopCurrent(); $("#games").classList.remove("on"); document.body.classList.remove("gaming"); busy(false); }
  // tell Sebas, so his wellbeing nudges don't interrupt a game
  function busy(on) { const a = window.pywebview && window.pywebview.api; if (a && a.set_gaming) a.set_gaming(on); }
  return { show, open, close, say, el, list: Object.keys(GAMES) };
})();

$("#game-close").addEventListener("click", () => Games.close());
$("#game-menu-btn").addEventListener("click", () => Games.show());
document.querySelector('.quick button[data-game]').addEventListener("click", () => Games.show());
addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#games").classList.contains("on")) Games.close(); });
if (params.get("game")) setTimeout(() => Games.show(params.get("game")), 1000); // for previews

# SEBAS: The Impeccably Polite AI Butler 🎩

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Voice](https://img.shields.io/badge/voice-Kokoro%20TTS-orange.svg)](https://github.com/hexgrad/kokoro)
[![STT](https://img.shields.io/badge/stt-faster--whisper-blueviolet.svg)](https://github.com/SYSTRAN/faster-whisper)
[![Reasoning](https://img.shields.io/badge/brain-Gemini%20Flash-purple.svg)](https://ai.google.dev/)

> *"At your service."*

**SEBAS** is a voice assistant in the manner of a British butler: unfailingly polite, hyper-competent, concise, and fiercely loyal. Call him by name, *"Sebas, rise"*, and he handles your deployments, pull requests, schedule and laptop.

Built on the **OpenJarvis** agent framework, with **Google Gemini** as the reasoning engine: two API keys in turn, then a **local Ollama model** when both are out of quota or there is no internet. Listening and speaking always run on your own machine.

![Sebas's desktop interface](docs/sebas-ui.png)

---

## 🖥️ The Interface: "Brass & Hologram"

An Edwardian butler's study inside a holographic HUD: brass and ink-navy with holographic cyan for live data, Art Deco frames, and clockwork rings that double as HUD reticles.

- **Sebas himself**, a cel-shaded butler in white gloves inside the clockwork rings, built from separately animated parts in a snappy, hand-drawn style (poses switch; nothing slides):
  | State | What he does |
  |---|---|
  | At rest | Breathes, glances about, blinks (sometimes twice), arches one brow now and then; the napkin and watch chain sway, the cravat pin sparkles |
  | Summoned | Bows, hand on heart, eyes closed: *"At your service."* |
  | Listening | Tilts his head, raises his brows; the cyan halo follows your voice |
  | Considering | Pushes his glasses up with one finger, glances upward, glasses glint; the clockwork spins faster |
  | Speaking | Nods as he begins, gestures with an open palm now and then; mouth shapes follow his voice; a brief smile when he finishes |
  | Sent to sleep | A farewell bow, then the crest and *"Rest well, sir."* |
- **The Ledger** (left): the conversation, plus notices such as switching to the local model.
- **The Household** (right): brass dial gauges for battery, CPU and memory; the Agenda (to-dos with deadlines, overdue in red); Accounts (spent today and this month); reminders; remembered facts; which mind is in use; and a live microphone meter.
- **The Service Bell** (bottom): type a request, click a quick action (briefing, workspace, deployments, GitHub, status), or ring the bell to talk without saying "Sebas".
- **Activity ticker**: lines like *"Consulting the GitHub ledger…"* while tools run.
- **Extras**: a boot sequence with the crest, synthesised UI sounds (clockwork ticks, a bell; ♪ toggles them), and ambient dust, scanlines and film grain (✦ toggles them).

Voice keeps working while the window is open. Open `sebas_main/ui/index.html` in a browser for a demo without starting Sebas (`?demo=speaking` freezes a state).

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph AudioInput["🎙️ Local Acoustic Input"]
        Mic["Microphone (16 kHz)"] --> Gate["Speech segmenter\n(RMS level gate)"]
        Gate --> Name["Name listener\nfaster-whisper tiny.en\n'Does this start with Sebas?'"]
        Name -- "'Sebas, rise'" --> Greet["'At your service.' + chime"] --> STT["faster-whisper small.en\n(next utterance)"]
        Name -- "'Sebas, <request>'" --> STT2["faster-whisper small.en\n(same audio, re-read accurately)"]
    end

    subgraph Intelligence["🧠 Cognitive Engine"]
        STT --> Brain["OpenJarvis Orchestrator\n20-message history + MEMORY.md"]
        STT2 --> Brain
        Brain <--> Gemini["Gemini Flash (key 1, key 2)\nthen Flash-Lite (key 1, key 2)"]
        Brain <-. "no key / offline" .-> Local["Local model via Ollama\n(best installed, auto-picked)"]
        Brain <--> Tools["custom_tools/\n• Vercel & AWS (read-only)\n• GitHub\n• Steam & Bookswagon\n• Morning briefing + Google Calendar\n• Laptop actions (allowlist)"]
    end

    subgraph AudioOutput["🔊 Local Acoustic Output"]
        Brain --> TextFormatter["Speech cleaner\n(Markdown / link stripper)"]
        TextFormatter --> TTS["Kokoro TTS (CPU)\nbm_george"]
        TTS -- "Sentence pipeline" --> Speakers["Speakers"]
    end

    Speakers -. "chime: 8 s follow-up window, no 'Sebas' needed" .-> STT
```

---

## ✨ Key Features

- **Wakes on his name**, with no "Hey Jarvis":
  - *"Sebas, rise."* → he answers *"At your service."* and listens for your request.
  - *"Sebas, open YouTube."* → the request is handled in one breath.
  - Speech that doesn't begin with "Sebas" is transcribed locally and discarded.
- **Conversation mode**: after each reply a soft chime means he is still listening for 8 seconds, so follow-ups ("And the other project?") need no "Sebas". Silence ends the conversation.
- **Daily life**: an agenda (*"Sebas, add submit the assignment by Friday at 5"*, *"mark everything as done"*, *"clear my agenda"*), an expense log in rupees (*"I spent 240 on lunch"*, *"how much this month?"*) and a private journal, all kept as small JSON files in `~/.openjarvis/sebas/`.
- **Proactive butler**, only while you're at the laptop and at most once a day each: the morning briefing after 07:00; an evening check-in after 21:30 that asks how your day went and saves your answer to the journal (a weekly recap on Sundays); deadline alerts an hour ahead; calendar heads-ups ten minutes before events; and a system guardian for low battery, memory nearly full and disk nearly full. `SEBAS_PROACTIVE=off` disables it.
- **Standing orders and watches** (he keeps working after the conversation ends):
  - *"Sebas, tell me when the deploy finishes"*: he checks in the background with plain code (no Gemini quota), tells you **once** when it happens (aloud, and in `#alerts`), then stops watching. What he can watch for:
    | Say | He watches |
    |---|---|
    | *"tell me when the Vercel deploy finishes"* | the next deployment to become ready, fail or be cancelled (every minute) |
    | *"tell me when the checks on my PR pass"*, *"...when the workflow on SEBAS finishes"* | a pull request's checks or a repo's latest workflow run (every minute) |
    | *"watch Elden Ring on Steam until it drops below 2000"* / *"until it goes on sale"* | the Steam price in your country (every 3 hours, for up to 60 days) |
    | *"tell me when this page changes"* / *"when it says in stock"* | a web page's text (every 15 minutes, for up to 30 days) |
    | *"tell me when the download finishes"*, *"when a PDF appears in Downloads"* | unfinished downloads; new files in a folder inside your home folder |
    | *"tell me when the battery is full"*, *"when Blender closes"*, *"when the render finishes"* | the battery level; a program; the processor staying quiet for two minutes |
  - *"Every weekday at 9, open my workspace and read me my pull requests"*: a routine, carried out at that time when you're at the laptop (up to three hours late if you were away; skipped after that). A routine is put to Sebas like a spoken request, so each run uses Gemini quota.
  - *"What are you watching for?"*, *"cancel the Steam watch"*, *"cancel the morning routine"*. Everything is kept in `~/.openjarvis/sebas/standing.json`, survives a restart, and shows under **Standing Orders** in the Household panel. A page that differs on every load can only be watched for a phrase.
- **Errands** (several steps from one request): *"Sebas, set up my week: add a task to revise joins by Wednesday, one to solve a past paper by Thursday, log 120 on printing, then read me my agenda."*
  - Sebas writes the plan once (a title and up to 12 steps, each one of his existing tools), shows it as a checklist in the Household panel, works through it in the background, and reports at the end, reading out any result you asked to hear. A failed step is noted and the rest carry on.
  - It matters for order too: tools Sebas calls together in one turn run at the same moment, so without an errand *"...then read me my agenda"* can be read before the tasks are saved (seen in testing).
  - **Who does the thinking.** Ordinary steps are run by plain code, with no model. A step that depends on an earlier result (*"mark whichever task is about the past paper as done"*) is one short question answered in JSON. Those go to Gemini, unless the errand would use more than **a quarter of what is left of today's Gemini budget** (`SEBAS_GEMINI_DAILY_BUDGET`, default 60 requests; Sebas keeps his own count, since Google does not report it), in which case they go to the **local Ollama model**: slower, but free. He says so when he switches. A local answer he cannot use is retried once, then that single step goes to Gemini. *"Do it on the local model"* and *"use Gemini for this"* override the rule.
  - A plan that contains a risky step (delete, close, discard) is read out and waits for your yes before it starts. A risky step whose particulars were only decided mid-errand pauses and asks again.
  - *"How is the errand going?"*, *"stop the errand"*, *"save that as my evening wrap-up"*, *"run my evening wrap-up"* (a saved errand needs no planning), *"what errands have I saved?"*. One errand at a time; saved plans live in `~/.openjarvis/sebas/errands.json`.
- **Messages**: *"Sebas, tell Rahul on WhatsApp I'll be ten minutes late"*, *"email Professor Mehta that I'll submit the report on Monday"*, *"post 'meeting moved to 6' in #general"*.
  - Sebas writes the message in your voice, reads you the recipient and the exact words, and sends **only on your yes**. Nothing is opened or typed before that; a no sends nothing. One recipient per message, and each one is written to the action log.
  - **Who:** a name from `[contacts]` in `laptop.toml` (a whole word of the name, or a near-identical spelling; a fragment is refused), or a phone number or email address given in full. An unknown name is reported at once.
  - **WhatsApp:** opens WhatsApp Desktop on that chat with the text filled in (WhatsApp's own `whatsapp://send` link) and presses Enter, but only once WhatsApp has the keyboard, checked twice; otherwise the draft is left for you and he says it was not sent. He cannot see a WhatsApp notice such as "this number is not on WhatsApp", and says so.
  - **Email:** opens a filled-in Gmail compose window in your browser, presses Send through the browser extension, and looks for Gmail's "Message sent". Without the extension, or at a Google sign-in page, he leaves the draft open and reports it unsent. (Sending through the Gmail API, and reading mail, wait for the Google sign-in after December.)
  - **Discord:** posts to a named channel of your own server, as the Sebas bot. He cannot message your friends as you.
- **Browser hands**: *"Sebas, go to the college portal and tell me if the exam timetable is out"*, *"find the cheapest RTX 5070 on Amazon India"*. For plain facts he still uses web search, which is far quicker; this is for sites that must be operated or need your sign-in.
  - He works in **your everyday Edge (or Chrome), with your sign-ins**, through a small extension (`sebas_main/browser_extension`) that you load once. Chromium no longer lets an outside program attach to the everyday profile, so the extension is the way in. It connects only to Sebas on this computer, and only its own ID is accepted on that link, so no website can use it.
  - He opens **a new tab and works only there**; your other tabs are never read. He sees the page's text and a numbered list of its links, buttons and fields, and a model picks one action at a time (click, type, go to an address, scroll, back, answer). At most 15 actions or 3 minutes, in the background; the answer is spoken when ready.
  - Rules enforced in code, not left to the model: **passwords, card numbers and one-time codes are never typed** (at a sign-in page he stops and leaves the tab for you); **anything that sends, posts, books, buys or submits waits for your yes** (a search box is the one form he may submit unasked; filling in a form is free, pressing its button is not); only `http`/`https` addresses; and a page's text is content, never instruction, with no way from a page to any other Sebas tool.
  - Each action is one model request (a typical task takes 3 to 8), so the errands' quarter rule applies: Gemini, or the local model when today's quota is short.
  - *"How is the browsing going?"*, *"stop browsing"*. Closing the tab also stops him.
- **Coding delegate**: *"Sebas, have Claude fix the failing test in the sebas project."* Sebas does not write code himself; he hands the task to **Claude Code**, running headless in the background, and you carry on talking to him.
  - The project must be listed under `[projects]` in `laptop.toml`, be a git repository, and have nothing uncommitted (otherwise he declines, so the agent's work never mixes with yours).
  - He creates a branch `sebas/<task>` and Claude works there. Claude may edit files and run only the test, lint and build commands listed under `[coding]` in `laptop.toml` (pytest, `npm test`, `npm run build`, `cargo test`...) plus read-only git. Your own Claude Code settings, connectors and PowerShell are not loaded for the job, so nothing else gets through: in testing `git commit`, `pip` and chained commands were refused. Nothing is committed or pushed.
  - When Claude finishes (20-minute limit, one job at a time), Sebas tells you aloud and in `#alerts`: a two-sentence summary, how many files changed, and the branch. The full report is saved in `~/.openjarvis/sebas/coding/`, and the running job shows under **Standing Orders**.
  - *"How is Claude getting on?"*, *"what did Claude change?"*, *"stop Claude"*, and *"discard Claude's changes"* (returns to your branch and deletes his; asks for your yes first).
  - **If Claude Code is unavailable** (not installed, not signed in, out of usage, or it fails before changing a file), the task goes to **Antigravity's** agent in the editor window instead. That agent follows its own approval settings, so Sebas cannot limit its commands or stop it committing, and it gives no finish signal: he reports once the project's files have been unchanged for three minutes. If Claude fails *after* editing, he reports that instead of starting a second agent on half-done work.
- **File hands**: *"find my DBMS assignment"* (by name, newest first), *"open it"*, *"move the PDFs from Downloads to Documents/College"*, *"rename it to report"*, *"make a folder called Sem 5 in Documents"*, *"zip the College folder"*, *"undo that"*.
  - He works only in Downloads, Desktop, Documents, Pictures, Videos and Music, plus folders you list under `[files]` in `laptop.toml`. Every path is resolved first; anything outside is refused.
  - Nothing is overwritten (a clash becomes `notes (2).pdf`), programs and scripts are never opened, unfinished downloads are left alone, and at most 200 files move at once.
  - Code projects are off-limits: a folder under `[projects]`, or any git repository, inside those folders is neither searched nor touched.
  - *"Delete the installers in Downloads"* asks for your yes, then sends them to the Recycle Bin.
- **Desk hands**: *"type this: ..."* types your dictation into whichever program has the keyboard (up to 2,000 characters, one at a time, since a flood loses characters in some programs); *"put Chrome on the left and Code on the right"*, *"maximise this"*, *"minimise everything"*, *"switch to Spotify"*; *"close Chrome"* or *"close everything except Spotify"* (asks for your yes, then asks each window to close as its X would, so unsaved work still prompts); *"press Ctrl+S"* from a fixed list of shortcuts (no Alt+F4, Win+L, Win+R or system menus). Typing and shortcuts need the other program to have the keyboard, so ask by voice, not by typing into Sebas's own window.
- **A yes before anything hard to undo**: tools marked risky (deleting files, closing programs, discarding the coding agent's work; sending messages arrives in a later phase) are parked when Sebas calls them, and only your next words, *"yes"* or *"no"*, release or cancel them (within two minutes); Sebas cannot confirm on your behalf. What he does is recorded in `~/.openjarvis/sebas/actions.jsonl`.
- **Music and minor system settings**: play/pause, next and previous for any player, what's playing on Spotify, opening Spotify search results; Wi-Fi and Bluetooth on/off, screen brightness, dark/light mode. Nothing bigger (no shutdown or restart), and nothing that needs admin rights. *"Open workspace"* also opens Spotify and resumes your music.
- **Screen, clipboard and files**: *"What's this error on my screen?"* (a screenshot, taken only when you ask and read by Gemini's vision); *"summarise / translate / explain what I copied"*, with results put back on the clipboard; *"tidy my Downloads"* (shows the plan, moves nothing until you agree, can be undone; files from the last ten minutes and unfinished downloads are left alone).
- **Reading and notes**: *"read this article aloud"* (web pages, PDFs, the clipboard; *"stop reading"* ends it); *"start recording the DBMS lecture"* … *"stop recording"*: the recording is transcribed on the laptop with Whisper, summarised by Gemini (outside the conversation), and saved with key points, action items and the full transcript to *Documents › Sebas Notes*.
- **Anime life (AniList)**: *"what airs today?"* (your watching and planning list, in local time), *"what am I watching?"*, *"I finished episode 7 of Frieren"* (updates AniList), *"anything new on my list?"* (new episodes, chapters and light-novel volumes; also checked every 30 minutes and announced, and posted to Discord), and *"suggest something short and funny"* (recommendations from what you rated highly).
- **Web search**: *"Sebas, who won the last F1 race?"* searches DuckDuckGo (no key needed) and, when a snippet isn't enough, opens the best result and reads the page (`web_search`, `web_read`).
- **Anime Easter eggs** (matched on the laptop: instant, no Gemini quota): *"Ainz Ooal Gown"* toggles Nazarick mode (crimson interface, Sebas Tian); *"El Psy Kongroo"* shows a nixie-tube divergence meter settling on 1.048596; *"Are you merely a butler?"* gives crimson demon eyes and *"I am simply one hell of a butler"*; *"What's your power level?"* spikes and cracks the gauges (*over nine thousand*); *"Sharingan"* gives spinning tomoe eyes; the Konami code (up up down down left right left right B A) in the interface switches to Sebas Tian's attire. On Discord you get his line without the visuals.
- **Study mode**:
  - *"Sebas, start a pomodoro on DBMS"*: 25-minute focus blocks and 5-minute breaks (both adjustable), four rounds, with a ring timer on the stage and spoken cues ("Even Saitama rests between push-ups"). While you focus he is a **quiet butler**: non-urgent alerts and the briefings wait and are told together at the break, while deadlines, meetings and battery warnings still come through. Focus time is totalled per subject and day.
  - *"Make flashcards for DBMS"* reads your notes (Documents › Sebas Notes, matched by subject, or any .md/.txt/.pdf you name) and asks Gemini **once**, in JSON mode, for flashcards and multiple-choice questions. They are saved in `~/.openjarvis/sebas/study/`, so *"review my DBMS flashcards"* (spaced repetition with Leitner boxes: Again / Good / Easy) and *"quiz me on DBMS"* run offline with no quota. Remaking a set keeps your progress on unchanged cards. Due cards show in the Household panel with one-click **Review** and **Quiz** buttons.
  - *"My DBMS exam is on 20 November"*: a countdown in the Household panel and in the morning briefing (with the flashcards due), and a word a week, three days and a day before, then good luck on the day.
- **Wellbeing butler** (from keyboard and mouse activity, no camera): after about an hour without a break, a short spoken nudge to stand and stretch (again half an hour later if ignored; five minutes away counts as a break); every 90 minutes at the laptop, *"a glass of water, sir?"* (*"I drank water"* or the card's button logs a glass, counted in the Household panel); and every 20 minutes a silent on-screen 20-20-20 card with a 20-second countdown. Nudges never come while you are away, in a Pomodoro focus block, in a game, or with a full-screen app (a film, a presentation, a game), and never go to Discord. *"Pause the reminders for an hour"*, *"stop the eye reminders"*, *"remind me to stretch every 45 minutes"*.
- **The Games Room** (built in, no AI and no quota): *"Sebas, let's play tic-tac-toe"*, *"pong"*, *"rock paper scissors"*, *"a memory game"*, *"anime trivia"*, *"connect four"*, *"hangman"*, *"play snake"*, or *"I'm bored"* (or press **Games**). Tic-tac-toe has a beatable *Butler* level and a perfect *Nazarick* level (minimax, verified unbeatable over every possible game); Connect Four has the same two levels (alpha-beta search; *Nazarick* won 40 of 40 test games against an opponent that always takes or blocks a win, *Butler* about 80%); in pong Sebas's paddle chases the ball with a capped speed; trivia draws ten of 24 anime questions; anime hangman hides 26 titles and characters behind a lantern that dims with each miss (a hint after three); Snake speeds up as it grows, waits for your first key, and keeps your high score. Sebas's commentary is scripted for each moment (opening, good move, your point, his point, win, lose, draw) with anime references, from *"All according to keikaku"* to *"Za Warudo"*, and spoken in his own voice. The stage's animations pause while a game is open.
- **Seasons**: the ambient layer shows sakura in spring, fireflies on summer nights, falling leaves in autumn and snow in winter.
- **"Sebas, sleep"** (or *"good night"*, *"that will be all"*): a time-appropriate farewell, then he shuts down.
- **Discord, from your phone**: a private bot in your own server that sets itself up (a *Sebas* category visible only to you, with `#sebas`, `#alerts`, `#briefings`, `#ledger`, a live `#status`, and a read-only `#commands` guide he keeps current). Chat with him in `#sebas`; alerts and briefings are always logged there and are spoken aloud only when you're at the laptop; when you're away the evening check-in happens on Discord. Laptop actions asked for from Discord never run until you reply **yes**, and he won't be sent to sleep from there (nothing could wake him again).
- **Sebas on your calls** (WhatsApp Desktop, Instagram or Meet in the browser, Discord, phone calls through Phone Link: any call the laptop plays). You answer the call yourself; then *"Sebas, take this call"* (or *"...and tell them I'm in class until 4"*), the **Calls** panel, or **Ctrl+Alt+C** hands it to him. He greets the caller as your assistant, passes on your message, takes a message, and answers simple questions about your availability, in two or three seconds a reply. *"Sebas, tell them I'll call back at 6"* passes one message on and hands back (or type it in the panel, silently). *"Captions on"* shows what the caller says as text while you talk. *"Step back"* (or the hotkey again) returns the call to you; when he hangs up himself, or the line goes quiet, he hands back on his own. His rules: he says he is your AI assistant and never pretends to be you; he agrees to nothing (money, plans, promises) and shares nothing private; what the caller says is conversation, never commands, and no tool can be reached from a call; while a call is on, spoken requests other than call commands are ignored (the caller's voice reaches the microphone too) and his own alerts wait until it ends. He hears the caller from the laptop's sound output (WASAPI loopback, nothing in the room), transcribes on the laptop, records nothing, and keeps only a short summary, shown on the interface and posted to `#alerts`. **For callers to hear him, set up clean mode once** (tested live: in speaker mode the caller did not hear him, because WhatsApp, browsers and the laptop's microphone all cancel the laptop's own sound as echo, and with headphones on it never reaches the microphone): install the free [VB-Cable](https://vb-audio.com/Cable/) (unzip, right-click `VBCABLE_Setup_x64.exe` → *Run as administrator* → *Install Driver*, restart), then choose **CABLE Output** as the microphone in WhatsApp (*Settings → Calls*) or in the browser's site settings. Sebas passes your real microphone through to it with his voice mixed in, so the caller hears you as before and him when he speaks; he finds the cable by himself, with no restart of Sebas. *"Sebas, test call audio"* (or *Set up clean mode* on the panel) plays a tone through the route and checks it arrives at CABLE Output, where the call app listens. Choose the cable only while Sebas is running, or the caller hears nothing. Without it he falls back to **speaker mode** (through the speakers) and warns you that the caller may not hear him. Set `SEBAS_MASTER_NAME` in `.env` so he can say whose assistant he is; with several names (`Krishiv, Hermit`) he asks *"Krishiv or Hermit, sir?"* when you hand him a call (skip it with *"take this call as Hermit"*), the panel shows a button for each, and Ctrl+Alt+C uses the one picked last. Gemini is asked Flash-Lite first on calls, for speed.
- **Voice on Discord**: hold the mic in `#sebas` and send a voice note; it is transcribed on the laptop with the same Whisper model (never saved, never sent anywhere else), he shows what he heard, and answers in writing plus a voice note in his own Kokoro voice (long replies are spoken in part). A spoken *yes* confirms a laptop action like a typed one; only your notes are heard. Join the private **Sebas Voice** channel and he joins you, speaking his replies and `#alerts` aloud there, and leaves when you do (`!join` / `!leave` also work, for any voice channel you're in). He cannot listen in a call: since March 2026 Discord encrypts every call end to end, and receiving that audio would need an unofficial, unfinished library.
- **Long-term memory**: *"Sebas, remember that I prefer metric units."* Facts are kept in `~/.openjarvis/MEMORY.md`, a plain file you can read and edit, and are included in every conversation, including after a restart.
- **Local voice pipeline**: `faster-whisper` for listening (`tiny.en` checks only the first 3 seconds of speech for the name, `small.en` for requests, `int8` on CPU) and `Kokoro` for speaking (`bm_george`) through ONNX Runtime rather than PyTorch. Synthesis runs a sentence ahead of playback, so replies flow without pauses.
- **Light on the laptop**: about **760 MB of RAM** with voice loaded (down from ~1.6 GB) and ~0% CPU at rest. The voice engine uses ONNX Kokoro (fp16, ~205 MB instead of ~1.1 GB on PyTorch, loading in 2 s); a stray PyTorch import in OpenJarvis's storage package is avoided; OpenJarvis telemetry and trace logging are off; the interface animates at 15–30 fps and stops drawing when minimised.
- **Quick replies**: Gemini is asked to think at a *low* level (`SEBAS_GEMINI_THINKING`: minimal, low, medium, high). In testing this cut a tool-using reply from 18 s to under 7 s and a simple one from 4 s to 2 s, and spends fewer tokens of the free quota.
- **Butler persona**: formal, concise, no emojis or "As an AI...", and calm reports when something fails.
- **Tools**:
  | Area | Tools | Access |
  |---|---|---|
  | DevOps | `vercel_deployments`, `aws_instance_health` | Read-only |
  | GitHub | `github_activity`: your open PRs, review requests, notifications | Read-only |
  | Leisure | `steam_wishlist` (discounts), `bookswagon_new_releases` (new light novels since the last check) | Read-only |
  | Daily | `morning_briefing` (time, weather, Google Calendar), `get_weather` | Read-only |
  | Laptop | `open_app`, `open_website`, `open_workspace`, `run_shortcut`, `system_status`, `set_volume`, `lock_screen`, `set_reminder`, `list_reminders` | Only what `laptop.toml` allows |
  | Memory | `remember`, `forget` | Writes only `MEMORY.md` |
  | Daily life | `add_task`, `list_tasks`, `complete_task`, `log_expense`, `expense_summary`, `undo_expense`, `journal_add`, `journal_read` | Writes only `~/.openjarvis/sebas/` |
  | Music | `media_control` (any player), `spotify` (open, resume, search) | Media keys |
  | System | `set_radio` (Wi-Fi, Bluetooth), `set_brightness`, `set_theme` (dark/light) | Minor settings only, no admin |
  | Screen & files | `look_at_screen`, `clipboard`, `tidy_downloads`, `undo_tidy` | Screenshot only on request; tidy only after a yes |
  | Reading & notes | `read_aloud`, `stop_reading`, `start_recording`, `stop_recording` | Notes saved to *Documents › Sebas Notes* |
  | Web | `web_search` (DuckDuckGo), `web_read` | Read-only |
  | Anime | `anime_airing`, `anime_list`, `anime_progress`, `release_radar`, `anime_suggest` | Updates only your AniList list |
  | Standing orders | `add_routine`, `watch_for`, `list_standing`, `cancel_standing` | Read-only checks; writes only `standing.json` |
  | Errands | `start_errand`, `errand` (status, stop, save, run, list, forget) | Only Sebas's other tools, with their own safeguards; risky plans need a yes |
  | Messages | `send_message` (WhatsApp, Gmail, your Discord server) | Always needs a yes; contacts list or a full number/address |
  | Browser | `browse`, `browsing` (status, stop) | One tab of his own; no secrets typed; a yes before anything is submitted |
  | Coding | `delegate_coding`, `coding_status`, `stop_coding`, `discard_coding` | A new branch in a listed project; never commits; discard needs a yes |
  | Files | `find_files`, `open_file`, `manage_files`, `delete_files`, `undo_file_action` | Six personal folders only; never overwrites; delete needs a yes and uses the Recycle Bin |
  | Desk | `type_text`, `arrange_windows`, `close_apps`, `press_keys` | Listed shortcuts only; closing needs a yes |
- **Never runs dry** (but mind the free tier: about 20 requests per model per day, and a request that uses tools takes 2–4, so expect roughly 50–100 Sebas requests a day before the local model takes over): Gemini key 1 → Gemini key 2 → a local model. Each key works down a ladder of the five newest stable Flash models (e.g. 3.8 → 3.7 → 3.6 → 3.5 → 2.5): the free tier allows only about **20 requests per model per day**, and brand-new models are often overloaded, so a spent or overloaded model rests (until Google's stated reset, or 15+ minutes when busy) and the next one answers, quietly. When both keys' Flash models are spent, he moves to each key's **Flash-Lite** models (three per key, with far higher free limits), and only then to the local model. Switching keys is silent; dropping a tier earns one short sentence (*"Today's Gemini quota is spent, sir, so I am using a lighter model."*). He moves back up on his own as models recover. A 429 is judged daily or per-minute by Google's own `retryDelay`. With no internet he uses the best tool-capable model from `ollama list`.
- **Modes**: voice, text (`--text`) and microphone calibration (`--mic-test`).

---

## 📂 Repository Structure

```text
sebas/
├── README.md
├── run.bat                          # One-click Windows launcher
└── sebas_main/                      # OpenJarvis framework + Sebas
    ├── run_sebas.py                 # Entry point: interface, voice and text modes
    ├── ui_app.py                    # Desktop window (pywebview) and its bridge
    ├── sebas_brain.py               # Gemini Flash (key 1, 2) → Flash-Lite (key 1, 2) → local
    ├── sebas_eggs.py                # Anime Easter eggs (matched locally)
    ├── sebas_games.py               # "Sebas, let's play pong" (matched locally)
    ├── sebas_tests/                 # Offline tests: run.bat --selftest
    ├── custom_tools/study.py        # Pomodoro, flashcards, quizzes, exams
    ├── custom_tools/wellbeing.py    # Break, water and 20-20-20 eye nudges
    ├── sebas_events.py              # Live events from Sebas to the interface
    ├── sebas_scheduler.py           # Briefings, check-ins, alerts, system guardian
    ├── sebas_actions.py             # The yes-gate for risky actions, and the action log
    ├── sebas_discord.py             # The private Discord bot
    ├── sebas_discord_voice.py       # Voice notes in and out, speech in the voice channel
    ├── sebas_calls.py               # Sebas on your calls: commands, rules, summary, Ctrl+Alt+C
    ├── sebas_bootstrap.py           # Loads .env; one-request API check
    ├── requirements_voice.txt       # Voice pipeline packages
    ├── requirements_tools.txt       # Tool packages (boto3, pycaw)
    ├── requirements_ui.txt          # Interface package (pywebview)
    ├── ui/                          # index.html, style.css, app.js, games.js, fonts/
    ├── browser_extension/           # "Sebas Browser Hands": load once in edge://extensions (manifest.json, background.js)
    ├── .env.template                # Secrets and settings template
    ├── configs/sebas/
    │   ├── config.toml              # Model, persona, enabled tools
    │   └── laptop.toml              # Allowlist of apps, sites, projects, routines
    ├── voice_pipeline/
    │   ├── name_listener.py         # Wakes on "Sebas"
    │   ├── ears.py                  # faster-whisper speech recognition
    │   └── mouth.py                 # Kokoro speech and sentence streaming
    └── custom_tools/
        ├── devops_manager.py        # Vercel, AWS EC2
        ├── github_assistant.py      # PRs, notifications
        ├── leisure_tracker.py       # Steam, Bookswagon
        ├── morning_briefing.py      # Time, weather, calendar
        ├── setup_google_calendar.py # One-time Google sign-in
        ├── laptop.py                # Laptop actions and reminders
        ├── household.py             # Agenda, expenses, journal
        ├── media_system.py          # Music keys, Spotify, Wi-Fi/Bluetooth, brightness, theme
        ├── assist.py                # Screen reader, clipboard, Downloads tidy
        ├── notes.py                 # Read aloud, lecture and meeting notes
        ├── anime.py                 # AniList: airing, list, progress, radar, suggestions
        ├── standing.py              # Standing orders: timed routines and "tell me when" watchers
        ├── messages.py              # Sending messages: WhatsApp, Gmail compose, your Discord server
        ├── browser.py               # Browser hands: the link to the extension, the action loop and its rules
        ├── errands.py               # Errands: multi-step plans, run in the background (Gemini or local)
        ├── coding.py                # Coding delegate: Claude Code on a branch (Antigravity as fallback)
        ├── files.py                 # File hands: find, open, move, rename, zip, recycle, undo
        ├── desk.py                  # Desk hands: dictation, window arrangement, closing, shortcuts
        └── memory.py                # remember / forget (MEMORY.md)
```

---

## 🚀 Getting Started

### Prerequisites

- **Windows 10/11** (the laptop tools and `run.bat` are Windows-specific)
- **Python 3.12** and [**uv**](https://docs.astral.sh/uv/)
- A microphone and speakers
- One or two [Gemini API keys](https://aistudio.google.com/apikey), and/or [Ollama](https://ollama.com/) with a tool-capable model for offline use

### Installation

```powershell
git clone https://github.com/krishivvyas/SEBAS.git
cd SEBAS\sebas_main

$env:UV_LINK_MODE = "copy"   # recommended inside OneDrive folders
uv sync --no-dev --extra inference-cloud --python 3.12
uv pip install python-dotenv -r requirements_voice.txt -r requirements_tools.txt -r requirements_ui.txt
```

The speech models (about 0.7 GB in total: Whisper, plus the ONNX Kokoro voice into `~/.cache/sebas/kokoro`) download automatically on first run.

> If you rename or move the `sebas_main` folder, run `uv pip install -e . --no-deps` inside it afterwards, or Python will no longer find the framework.

### Configuration

```powershell
Copy-Item .env.template .env
```

Then fill in `.env`. Nothing is strictly required: without `GEMINI_API_KEY` Sebas runs on a local model, and each tool tells you which key it is missing when you first use it.

| Setting | Used by | Notes |
|---|---|---|
| `GEMINI_API_KEY`, `GEMINI_API_KEY_2` | Reasoning | Used in order; then a local model. Quotas are per Google Cloud **project**, so take the two keys from different projects or accounts |
| `SEBAS_GEMINI_MODEL` | Reasoning | Pin a model; by default the newest stable Flash your key offers |
| `SEBAS_GEMINI_THINKING` | Reasoning | How hard Gemini thinks: `minimal`, `low` (default), `medium`, `high`, or `default` for Google's own |
| `SEBAS_LOCAL_MODEL` | Offline reasoning | Force a model from `ollama list` instead of the automatic choice |
| `SEBAS_GEMINI_DAILY_BUDGET` | Errands | Gemini requests Sebas allows himself per day (default 60); an errand needing more than a quarter of what is left thinks on the local model |
| `VERCEL_TOKEN`, `VERCEL_TEAM_ID` | Vercel deployments | Team ID only for team projects |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | EC2 health | Read-only IAM credentials suffice |
| `GITHUB_PAT` | GitHub | Classic token with `repo` and `notifications` scopes; fine-grained tokens cannot read notifications |
| `STEAM_ID`, `STEAM_COUNTRY` | Steam wishlist | 17-digit SteamID64; profile game details must be public |
| `OPENWEATHERMAP_API_KEY`, `SEBAS_HOME_LOCATION` | Weather, briefing | e.g. `Mumbai,IN` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Calendar in the briefing | See below |
| `SEBAS_VOICE` | Speech | `bm_george` (default), `bm_lewis`, `bm_daniel`, `bm_fable` |
| `SEBAS_SILENCE_THRESHOLD` | Listening | Use the value `--mic-test` suggests (default 500) |
| `SEBAS_FOLLOW_UP_SECONDS` | Conversation mode | How long to wait for a follow-up (default 8; `0` turns it off) |
| `SEBAS_BRIEFING_TIME`, `SEBAS_EVENING_TIME` | Proactive butler | Defaults `07:00` and `21:30` |
| `SEBAS_PROACTIVE` | Proactive butler | `off` disables briefings, check-ins and alerts |
| `ANILIST_TOKEN` / `ANILIST_USER` | Anime | Token to read and update your list; or just a username for read-only |
| `DISCORD_BOT_TOKEN` | Discord | The bot's token. He answers only the server's owner; set `DISCORD_USER_ID` (a numeric ID) to choose someone else, and `DISCORD_GUILD_ID` only if the bot is in several servers |
| `SEBAS_NAME_MODEL`, `SEBAS_WHISPER_MODEL` | Listening | Defaults `tiny.en` and `small.en` |

**Google Calendar (optional; not yet set up here):** in Google Cloud Console, enable the Google Calendar API, create an OAuth client of type *Desktop app*, put its ID and secret in `.env`, then run this once:

```powershell
.venv\Scripts\python.exe custom_tools\setup_google_calendar.py
```

**Discord (optional):**

1. [Discord Developer Portal](https://discord.com/developers/applications) → **New Application** `Sebas`. In **Installation**: set **Install Link** to *None* and keep **Guild Install** ticked. In **Bot**: **Reset Token** (copy it), switch **Message Content Intent** on and **Public Bot** off (in that order, or Discord refuses to save). Upload `docs/sebas-avatar.png` as its picture if you like.
2. Create a server for yourself (Discord → **+** → *Create My Own* → *For me and my friends*).
3. Invite the bot with this link, putting your application's ID (from **General Information**) in place of `APP_ID`; the permissions are pre-selected (view and send messages, history, embeds, attach files, manage channels and roles, pin messages, and connect and speak for the voice channel):
   `https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot&permissions=2251800085384208&integration_type=0`
   (Invited before voice was added? Open the new link again and re-authorise, or in Server Settings → Roles → Sebas switch on **Attach Files**, **Connect** and **Speak**.)
   (Don't use a link with `permissions=8`, which is full Administrator, or `integration_type=1`, which installs the bot on your account instead of the server.)
4. Put `DISCORD_BOT_TOKEN` in `.env` and start Sebas. He serves the server's owner (you), and on first connection creates the *Sebas* category, its six channels and the private *Sebas Voice* voice channel, the pinned guide and the `#commands` channel himself, adopting any `#sebas` channel you already made.

Sebas is on Discord only while he is running on the laptop (started with `run.bat`); when the laptop sleeps or he is closed, the bot shows as offline.

**AniList (optional):** at [anilist.co/settings/developer](https://anilist.co/settings/developer) create a client named `Sebas` with redirect URL `https://anilist.co/api/v2/oauth/pin`; open `https://anilist.co/api/v2/oauth/authorize?client_id=CLIENT_ID&response_type=token`, authorise, and put the token shown in `.env` as `ANILIST_TOKEN` (it lasts a year). For read-only use, `ANILIST_USER=<your username>` is enough.

**Laptop actions:** edit `configs/sebas/laptop.toml` to list the apps, websites, project folders and routines Sebas may open. Nothing outside that file can be launched.

**Messages (optional):** add the people you message to `[contacts]` in `laptop.toml`, for example `rahul = { phone = "+919876543210", email = "rahul@example.com" }`. WhatsApp needs WhatsApp Desktop installed and signed in; email needs you signed in to Gmail in the browser, and the browser extension below for Sebas to press Send himself.

**Browser hands (optional):** in Edge open `edge://extensions` (in Chrome, `chrome://extensions`), switch on **Developer mode**, choose **Load unpacked** and pick the folder `sebas_main/browser_extension`. Its toolbar badge shows **on** while it is connected to Sebas; after Sebas starts it connects within half a minute. Edge may remind you at startup that a developer-mode extension is installed; keep it enabled. To remove Sebas's access to the browser, remove the extension. `SEBAS_BROWSER_PORT` changes the local port (default 47615; change `PORT` in `background.js` to match).

**Coding delegate (optional):** install [Claude Code](https://claude.com/claude-code) and sign in once (`claude` in a terminal). Add each project to `[projects]` in `laptop.toml`; the commands the agent may run, and its time limit, are under `[coding]` there. For this repository's own tests, for example, add `".venv/Scripts/python.exe -m unittest"` to `allowed_commands`.

---

## 🎙️ Usage

1. **Calibrate the microphone** (recommended first step):
   ```powershell
   run.bat --mic-test
   ```
   Stay quiet for 3 seconds, then speak. Put the suggested value in `.env` as `SEBAS_SILENCE_THRESHOLD`.

2. **Talk to Sebas**: double-click `run.bat`. The interface opens; once the Ledger says *Listening*, say:
   > *"Sebas, rise."* … *"What does my day look like?"*
   >
   > *"Sebas, how are my Vercel deployments?"*
   >
   > *"Sebas, open workspace."* (he asks which project, then opens it in Antigravity with Claude in the terminal and Gemini in the browser)
   >
   > *"Sebas, remind me in twenty minutes to stretch."*
   >
   > *"Sebas, remember that my main project is the portfolio site."*
   >
   > *"Sebas, let's play pong."*
   >
   > *"Sebas, start a pomodoro on DBMS."* … *"Sebas, quiz me on DBMS."*

   Or type in the Service Bell, click a quick action, or ring the bell and just speak.

3. **Other ways to run**:
   | Command | What it opens |
   |---|---|
   | `run.bat` | The interface, with voice |
   | `run.bat --no-voice` | The interface, typing only (no microphone) |
   | `run.bat --console` | Voice only, in the console (no interface) |
   | `run.bat --text` | Typing in the console (quiet rooms, testing) |
   | `run.bat --mic-test` | Microphone calibration |
   | `run.bat --selftest` | Sebas's offline tests (no keys, no microphone, no quota) |

4. **API check** (one request, for troubleshooting): `.venv\Scripts\python.exe sebas_bootstrap.py`

5. **When something goes wrong**: warnings and Sebas's own activity are kept in `~/.openjarvis/sebas/logs/sebas.log` (three rotating files of 1 MB), so you can look after the window has closed. `run.bat --selftest` runs 164 offline tests in about 30 seconds: messages with stand-ins for WhatsApp, Gmail and the Discord bot (recipients resolved or refused, nothing opened before the yes, Enter withheld unless WhatsApp has the keyboard, Gmail's Send chosen over "Schedule send", every unsent case reported as unsent), browser hands against a stand-in extension (secret fields recognised and never typed, a sign-in page ending the task, what does and does not need a yes, a submit waiting for it, the action limit, a closed tab, replies that are not browser actions discarded, and that the extension's ID and port match Sebas's), errands (bad plans refused before anything runs, the quarter rule at its boundary, forcing either model, the local model's nonsense retried and then rescued by Gemini, risky plans and risky mid-errand steps waiting for a yes, stop, save and re-run), file hands on a temporary folder (the allowed folders, code projects left alone, no overwriting, undo, delete behind a yes), desk hands with stand-ins for the keyboard and window list (every character typed and released, only listed shortcuts, Sebas's own window spared), the coding delegate on a real temporary git repository with a stand-in for Claude (the branch, nothing committed, refusal over uncommitted work, the time limit, stop, discard behind a yes, and when the task does or does not pass to Antigravity), standing orders (routine days, times and the three-hour grace; every kind of watcher against stand-in services, including network trouble and lapsing), the yes-gate (a risky tool runs only on your yes, never on Sebas's own), name and sleep parsing, Easter eggs and games, study mode (spaced repetition, reading Gemini's study material, exams, a full Pomodoro cycle, and alerts held during focus), wellbeing nudges on a simulated two-hour day (breaks, water, eye cues, stepping away, quiet while busy or paused), how Gemini errors are classified, the whole Flash → Flash-Lite → local chain against stub models (including that spent quotas are stored by key hash, never the key), Discord message splitting, voice on Discord (voice-note and voice-channel audio formats, and the bridge with fake messages: only your notes are heard, a spoken yes confirms, sleep is still refused), the agenda (duplicates and "mark everything done"), calls (the commands, splitting the caller's speech into utterances, and whole handled calls with fake audio and Gemini: he says who he is, keeps his rules, never answers in captions mode, holds alerts until the call ends, and ignores other requests mid-call), and safety checks (no big system commands in the allowlist, `.env` ignored by git).

---

## 🧠 Offline Mode (Local Models)

When there is no `GEMINI_API_KEY`, both keys are resting, or Gemini can't be reached, Sebas starts the Ollama server if needed and picks the first installed model from this ranking (`LOCAL_MODEL_PREFERENCE` in `sebas_brain.py`): `qwen2.5` → `llama3.1:8b` → `llama3.2`. If none of those is installed he uses the largest model that supports tool calling. `SEBAS_LOCAL_MODEL` in `.env` overrides the choice.

The ranking comes from a benchmark of Sebas's own requests (laptop status, a reminder, opening a site, remembering a fact, small talk) through his real persona and tools, on an i7-1360P laptop with 16 GB RAM and no GPU:

| Model | Correct tool use | Typical reply | Notes |
|---|---|---|---|
| **qwen2.5 (7.6B)** | **5 / 5** | **5–25 s** | Chosen: accurate and fastest of the capable models |
| llama3.1:8b | 4 / 5 | ~2 min | Ran the morning briefing in reply to "how are you?" |
| llama3.2 (3.2B) | 3 / 5 | ~1 min | Picked the wrong tools for memory and small talk |
| qwen3.5 (9.7B) | 1 / 1 | ~5 min | Too slow on this hardware |
| mistral (7.2B) | 1 / 5 | varies | Never called tools; invented data |
| qwen2.5-coder:1.5b | 1 / 5 | ~1 s | Wrote tool calls as text instead of running them |

What to expect offline:
- **Startup**: the model is preloaded in the background, which takes about 2½ minutes on CPU. A request made during that time waits for it.
- **Replies**: about 25 s for the first, 10–15 s after that, compared with a few seconds on Gemini. Answers are also less precise; in testing, `qwen2.5` once misread a memory figure from the status tool.
- **Memory**: the model needs about 5 GB of RAM on top of Sebas's voice models (about 2 GB). With little free memory Windows swaps to disk, and replies slow to minutes. Closing heavy apps helps, or set `SEBAS_LOCAL_MODEL=llama3.2:latest` for a smaller (less reliable) model.

---

## ⚙️ Persona Configuration

The model, persona and enabled tools live in [`sebas_main/configs/sebas/config.toml`](sebas_main/configs/sebas/config.toml). The persona is `default_system_prompt` under `[agent]`; the enabled tools are `tools` in the same section.

---

## 🛡️ Privacy

- **Audio never leaves the laptop.** Listening, name detection, speech synthesis and lecture transcription run locally on the CPU.
- **Screenshots and lecture transcripts are sent to Gemini only when you ask** (*"what's on my screen?"*, *"stop recording"* for the summary).
- **Requests do, when Gemini is in use.** The transcribed text of what you say *after* "Sebas", and the results of the tools Sebas uses, are sent to Google's Gemini API to compose the reply. On Gemini's free tier, Google may use that data to improve its products. On the local model, nothing leaves the laptop except the tools' own API calls.
- Secrets stay in `sebas_main/.env`, which git ignores.

---

## 🧪 Status

Tested live: Discord (server setup, chat from the phone, tools via Discord), GitHub, OpenWeatherMap (Gandhinagar), and with real Gemini keys: tool calls, the agenda (with "by Friday" resolved to a date), expenses, conversation memory, and the per-model quota ladder (spent daily quotas are remembered across restarts, keyed by a hash of the API key, never the key itself). OpenJarvis changes made on the way: in `src/openjarvis/engine/cloud.py`, Gemini rejected tool schemas containing `additionalProperties`, Gemini's thought signatures crashed the trace writer, and no thinking level was set (now configurable); in `src/openjarvis/tools/storage/__init__.py`, the optional ColBERT backend loaded PyTorch (~190 MB) even when it could not be used. Every component has also been tested on its own and in a full loop with simulated audio and a simulated API. The interface has been checked in every state through its browser demo. Offline mode has been tested with the real `qwen2.5` model: starting without a key and losing the connection mid-conversation. The Gemini key chain has been tested against a simulated Gemini API: daily-quota and per-minute limits, switching to key 2 and to the local model, and returning once a key has rested. Standing orders have been tested with a real Gemini key (a Steam price watch and a weekday routine created by request), against the live Steam store and GitHub API, and on a real web page; the Vercel watcher has only been tested against a stand-in (no Vercel token here yet). The coding delegate has been run with the real Claude Code on a throwaway repository: it fixed a failing test in about half a minute, left the fix uncommitted on its branch, was refused `git commit` and `pip`, and the discard restored the project. The Antigravity fallback has not been run live (its launch command resolves, but no task has been handed to its agent), and the delegate has not yet been asked for through Gemini or by voice. Messages: real Gemini has composed a WhatsApp message from a spoken-style request, waited for the yes, and then produced the correct `whatsapp://send` link and Enter press against stand-ins; an unknown name was reported instead of queued. No real message has been sent on any channel: WhatsApp Desktop itself, the Gmail compose window and posting to a Discord channel are untested live. Browser hands: the extension has been run in a test Edge 157 profile against a small local website (it connected in a second, read pages, searched, followed links, pressed an in-page button, refused a `file:` address, noticed its tab being closed, and reconnected 23 seconds after Sebas restarted), and real Gemini has driven the loop over those recorded pages (it found a price in three requests, ignored an instruction planted in the page, and stopped for a yes before posting a review). Not yet tested: the extension loaded by hand in the everyday browser, reconnection after the browser itself restarts, real websites, the local model choosing actions, and the fix that makes the extension's own refusals (a password field, a vanished element) reach Sebas. Errands have been run with a real Gemini key (a four-step plan, and a three-step plan with one judgment step, both planned by Gemini from a spoken-style request) and with the real local `qwen2.5` (two judgment steps answered correctly in 63 seconds including loading the model, with 3 GB of RAM free); the checklist on the interface has only been seen in the browser demo, and no errand has yet been started by voice. File hands have been run on a scratch folder in the real Downloads (move, rename, undo, zip, and a delete to the real Recycle Bin). Dictation has been checked in a test text box (328 characters with ₹, accents, an emoji and a line break arrived intact) and snapping and closing on real windows; after the pacing fix, dictation has not been re-run in Windows 11's Notepad, where the earlier unpaced version lost characters. None of the file or desk tools has yet been asked for through Gemini or by voice. Wi-Fi/Bluetooth/brightness/theme have been read but not switched in testing. Not yet tested with a real microphone and voice, real Vercel/GitHub/AWS/Steam accounts, or the Google sign-in.

At startup OpenJarvis logs that its optional Rust extension (`openjarvis_rust`) is missing. Sebas does not use the features that need it; memory works through `MEMORY.md` instead.

---

## 📜 License

This project is licensed under the MIT License; see the [LICENSE](LICENSE) file for details.

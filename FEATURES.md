# Sebas: Feature List

Every feature Sebas has, what to say to use it, and whether it needs a model to think. The [README](README.md) explains setup and how each feature works in detail.

**Model column**

| Mark | Meaning |
|---|---|
| ⚙️ | Plain code on the laptop. No Gemini request, no quota. |
| 🧠 | A spoken or typed request goes to Gemini (or the local Ollama model when the quota is spent or there is no internet). Gemini understands what you asked, picks the tool and words the reply, usually in 1 to 4 requests. The tool itself still runs on the laptop. |
| 🧠×1 | Gemini is asked once more inside the tool (to summarise, read a screenshot, make flashcards). |

Any request you speak goes through 🧠, except the ones in [Answered on the laptop](#answered-on-the-laptop-no-model). Work done in the background (tracking, watching, timers) is ⚙️.

---

## Waking and talking

| Feature | Say | Model |
|---|---|---|
| Wake on his name | *"Sebas, rise."*, *"सेबास, उठो"*, or *"Sebas, open YouTube."* | ⚙️ (local Whisper) |
| Follow-up without "Sebas" | Speak within 8 s of the chime | ⚙️ |
| Ring the bell / type a request | Service Bell at the bottom of the window | 🧠 |
| Mute / unmute the microphone | 🎙 button beside the bell | 🧠 |
| Go to sleep | *"Sebas, sleep"*, *"good night"*, *"that will be all"* | ⚙️ |
| Long-term memory | *"Remember that I prefer metric units"*, *"forget that"* | 🧠 |
| Web search | *"Who won the last F1 race?"* | 🧠 |

## Languages

| Feature | Say | Model |
|---|---|---|
| Speak Hindi or Gujarati | *"सेबास, आज मेरा एजेंडा क्या है?"*, *"સેબાસ, આજે મારા કામ શું છે?"* | ⚙️ to detect the language (local Whisper); 🧠 for the reply, in the same language |
| Language switch notice | Automatic: *"Switching back to English, sir."* | ⚙️ |
| Hindi and Gujarati voices | Automatic, per sentence | ⚙️ (Kokoro Hindi, MMS Gujarati, on the laptop) |
| Yes / no in Hindi and Gujarati | *"हाँ"*, *"ठीक है"*, *"હા"*, *"नहीं"*, *"ના"* | ⚙️ |

## Daily life

| Feature | Say | Model |
|---|---|---|
| Agenda | *"Add submit the assignment by Friday at 5"*, *"mark everything as done"*, *"clear my agenda"* | 🧠 |
| Expenses (₹) | *"I spent 240 on lunch"*, *"how much this month?"*, *"undo that expense"* | 🧠 |
| Journal | *"Add to my journal: …"*, *"read my journal"* | 🧠 |
| Reminders | *"Remind me in twenty minutes to stretch"* | 🧠 |
| Morning briefing | *"What does my day look like?"*; also automatic after 07:00 | 🧠 |
| Evening check-in and weekly recap | Automatic after 21:30 (Sundays: the week) | 🧠 |
| Deadline alerts, system guardian | Automatic: an hour before a deadline; low battery, memory or disk | ⚙️ |
| Weather | *"What's the weather?"* | 🧠 |

## Your day, on record

| Feature | Say | Model |
|---|---|---|
| Screen-time diary (the tracking) | Nothing; runs while you're at the laptop | ⚙️ |
| Screen-time questions | *"How long was I on YouTube today?"*, *"my screen time this week?"* | 🧠 |
| Daily limit | *"Limit YouTube to an hour a day"* (the warning itself is ⚙️) | 🧠 |
| What did I do today | *"What did I do today?"* | 🧠 (the tool gathers everything with no extra request) |
| Bedtime wind-down | *"Bedtime at midnight"*, *"no bedtime reminder"*; the wind-down is automatic | 🧠 to set, ⚙️ to run |

## Search my stuff

| Feature | Say | Model |
|---|---|---|
| Search notes, Documents, journal, flashcards | *"What did I note about normalisation?"* | 🧠 (the search itself is ⚙️; Gemini answers from the passages found) |

## Standing orders and watches

| Feature | Say | Model |
|---|---|---|
| Set a watch | *"Tell me when the deploy finishes"*, *"…when Blender closes"*, *"…when a PDF appears in Downloads"*, *"watch Elden Ring until it drops below 2000"* | 🧠 to set |
| The watching | Checks every minute to every 3 hours, tells you once | ⚙️ |
| Routine | *"Every weekday at 9, open my workspace and read me my pull requests"* | 🧠 to set, and 🧠 every time it runs |
| List / cancel | *"What are you watching for?"*, *"cancel the Steam watch"* | 🧠 |

## Errands (several steps from one request)

| Feature | Say | Model |
|---|---|---|
| Plan and run | *"Set up my week: add a task…, log 120 on printing, then read me my agenda"* | 🧠 to plan once; ordinary steps ⚙️ |
| A step that depends on an earlier result | *"…mark whichever task is about the past paper as done"* | 🧠×1 per such step (Gemini, or the local model when today's budget is short) |
| Status, stop, save | *"How is the errand going?"*, *"stop the errand"*, *"save that as my evening wrap-up"* | 🧠 |
| Run a saved errand | *"Run my evening wrap-up"* | 🧠 to ask; no planning again |

## Hands on the laptop

| Feature | Say | Model |
|---|---|---|
| Open apps, sites, workspace | *"Open workspace"*, *"open YouTube"* | 🧠 |
| Files | *"Find my DBMS assignment"*, *"move the PDFs from Downloads to Documents/College"*, *"zip the College folder"*, *"undo that"* | 🧠 |
| Delete files (asks for a yes) | *"Delete the installers in Downloads"* | 🧠 |
| Tidy Downloads (asks for a yes) | *"Tidy my Downloads"* | 🧠 |
| Dictation | *"Type this: …"* | 🧠 |
| Windows | *"Put Chrome on the left and Code on the right"*, *"maximise this"*, *"switch to Spotify"* | 🧠 |
| Close programs (asks for a yes) | *"Close Chrome"*, *"close everything except Spotify"* | 🧠 |
| Shortcuts | *"Press Ctrl+S"* (listed shortcuts only) | 🧠 |
| Music | *"Pause"*, *"next song"*, *"what's playing?"* | 🧠 |
| Settings | *"Turn Wi-Fi off"*, *"brightness 50"*, *"dark mode"* | 🧠 |
| Screen | *"What's this error on my screen?"* | 🧠 + 🧠×1 (Gemini reads the screenshot) |
| Clipboard | *"Summarise / translate / explain what I copied"* | 🧠 + 🧠×1 |

## Messages (always ask for a yes)

| Feature | Say | Model |
|---|---|---|
| WhatsApp | *"Tell Rahul on WhatsApp I'll be ten minutes late"* | 🧠 |
| Email (Gmail compose) | *"Email Professor Mehta that I'll submit the report on Monday"* | 🧠 |
| Discord channel | *"Post 'meeting moved to 6' in #general"* | 🧠 |

## Browser hands

| Feature | Say | Model |
|---|---|---|
| Operate a website | *"Go to the college portal and tell me if the exam timetable is out"*, *"find the cheapest RTX 5070 on Amazon India"* | 🧠, then 🧠×1 for every click or typing step (typically 3 to 8) |
| Status / stop | *"How is the browsing going?"*, *"stop browsing"* | 🧠 |

## Coding

| Feature | Say | Model |
|---|---|---|
| Hand a task to Claude Code | *"Have Claude fix the failing test in the sebas project"* | 🧠 to ask; the work is done by Claude Code (your Claude usage, not Gemini) |
| Status, changes, stop, discard | *"How is Claude getting on?"*, *"what did Claude change?"*, *"discard Claude's changes"* | 🧠 |
| PR review | *"Have Claude review my open PR in sebas"* | 🧠 + Claude Code |
| DevOps and GitHub | *"How are my Vercel deployments?"*, *"any PRs waiting for me?"* | 🧠 |

## Study and wellbeing

| Feature | Say | Model |
|---|---|---|
| Pomodoro | *"Start a pomodoro on DBMS"* (the timer and cues are ⚙️) | 🧠 to start |
| Make flashcards | *"Make flashcards for DBMS"* | 🧠 + 🧠×1 |
| Review / quiz | *"Review my DBMS flashcards"*, *"quiz me on DBMS"* | 🧠 to start; the review runs offline |
| Exams | *"My DBMS exam is on 20 November"* | 🧠 |
| Break, water and eye nudges | Automatic; *"pause the reminders for an hour"* | ⚙️ (🧠 to change them) |
| Read aloud | *"Read this article aloud"*, *"stop reading"* | 🧠 |
| Lecture notes | *"Start recording the DBMS lecture"* … *"stop recording"* | 🧠 + 🧠×1 (transcription is ⚙️ Whisper; Gemini summarises) |

## Anime and leisure

| Feature | Say | Model |
|---|---|---|
| AniList | *"What airs today?"*, *"I finished episode 7 of Frieren"*, *"suggest something short and funny"* | 🧠 |
| New releases check | Automatic every 30 minutes | ⚙️ |
| Steam, Bookswagon | *"Anything on sale on my wishlist?"*, *"new light novels?"* | 🧠 |

## Calls

| Feature | Say | Model |
|---|---|---|
| Hand a call to Sebas | *"Sebas, take this call"*, Ctrl+Alt+C, or the Calls panel | 🧠 for every reply to the caller (Flash-Lite first, for speed) |
| Pass on a message | *"Tell them I'll call back at 6"* | 🧠 |
| Captions | *"Captions on"* | ⚙️ (local Whisper) |
| Take the call back | *"Step back"* or Ctrl+Alt+C | ⚙️ |

## Discord

| Feature | Say | Model |
|---|---|---|
| Chat from your phone | Write in `#sebas` | 🧠 |
| Voice notes | Hold the mic in `#sebas` | 🧠 (transcribed on the laptop) |
| Voice channel | Join *Sebas Voice*, or `!join` / `!leave` | 🧠 for each reply |

## Answered on the laptop (no model)

These are recognised on the laptop and answered instantly, with no Gemini request.

| Feature | Say |
|---|---|
| Games | *"Let's play tic-tac-toe"*, *"pong"*, *"connect four"*, *"hangman"*, *"play snake"*, *"anime trivia"*, *"I'm bored"* |
| Easter eggs | *"Ainz Ooal Gown"*, *"El Psy Kongroo"*, *"Are you merely a butler?"*, *"What's your power level?"*, *"Sharingan"*; the Konami code in the window |
| Wake and sleep | *"Sebas, rise"*, *"Sebas, sleep"* |

## Safety rules that apply everywhere

- **A yes before anything hard to undo**: deleting files, closing programs, sending messages, discarding Claude's work, risky errands, and anything the browser would submit. Only your own *"yes"* within two minutes releases it. Everything done is logged in `~/.openjarvis/sebas/actions.jsonl`.
- **Allowlists**: apps, sites, projects, contacts and extra folders come from `sebas_main/configs/sebas/laptop.toml`.
- **Never typed**: passwords, card numbers and one-time codes.

---

## Which version added what

Current version: **v1.11.2**. A short list of every version is in [VERSIONS.md](VERSIONS.md); the full history, with commits, is in the [README](README.md#️-version-history).

| Version | Features added |
|---|---|
| v1.11.2 | VERSIONS.md |
| v1.11.1 | Documentation brought up to date |
| v1.11.0 | English, Hindi and Gujarati (detected per sentence, replies and voices in each, models loaded only when used); listening fixes (longer pauses, misheard "rise", timing in the log) |
| v1.10.4 | Calls panel layout fixed; Ear meter moved under the gauges; speaker-mode troubleshooting in the README |
| v1.10.3 | LICENSE file (MIT) |
| v1.10.2 | README reformatted; this version list |
| v1.10.1 | This file (FEATURES.md) |
| v1.10.0 | Screen-time diary and limits, what did I do today, bedtime wind-down, search my stuff, PR review |
| v1.9.0 | Messages (WhatsApp, email, Discord channel), browser hands |
| v1.8.0 | Errands |
| v1.7.0 | Standing orders and watches, coding delegate, file hands, desk hands, the yes-gate |
| v1.6.1 | Call audio (clean mode) |
| v1.6.0 | Sebas on your calls, voice on Discord |
| v1.5.1 | Agenda fixes (duplicates, mark everything done) |
| v1.5.0 | Study mode, wellbeing butler, Games Room, web search |
| v1.4.0 | Gemini brain, Discord bot, proactive butler, agenda/expenses/journal, music and system settings, screen and clipboard, Downloads tidy, read aloud, lecture notes, AniList, Easter eggs |
| v1.3.0 | Desktop interface, conversation follow-up |
| v1.2.0 | Local model and offline mode |
| v1.1.0 | Voice pipeline (wake on name, listening, speaking), DevOps, GitHub, Steam, Bookswagon, morning briefing, laptop actions, memory |
| v1.0.0 | First commit |

---

## Not built yet

| Idea | Status |
|---|---|
| Google Calendar, Gmail inbox (read, summarise, reply) | Waiting for a new Google Cloud project, after 7 December 2026 |
| Voice lock (only your voice wakes him or says yes) | Saved for later |
| Nightly backup of `~/.openjarvis/sebas` to OneDrive | Saved for later |
| Monthly budgets per expense category | Saved for later |

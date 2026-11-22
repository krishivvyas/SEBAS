# Sebas: Versions

Every version of Sebas, newest first. **v1.N.0** adds features; **v1.N.x** is documentation, fixes and small changes. Full details are in the [README](README.md#️-version-history) and [FEATURES.md](FEATURES.md).

**Current version: v1.11.2**

---

### v1.11.2 · 2026-11-22 · `c2617a8`
- This file (VERSIONS.md): every version with what it added, linked from README and FEATURES.md.

### v1.11.1 · 2026-11-22 · `c51f820`
- Documentation brought up to date: architecture diagram, RAM figures, the 213 offline tests, folder layout, `run.bat` notes.
- Live results recorded: calls in clean mode, and the Hindi/Gujarati measurements.

### v1.11.0 · 2026-11-22 · `f3315e5`
- **English, Hindi and Gujarati**: language detected per sentence, replies in the same language, and Sebas says when he switches; Hindi/Gujarati models load only when used and unload after 10 idle minutes.
- **Hindi and Gujarati voices** (Kokoro `hm_omega`, Meta's MMS Gujarati), and yes/no in all three languages.
- **Listening fixes**: 1.2 s pauses allowed, 25 s requests, misheard "rise" understood, timing of each request in the log.

### v1.10.4 · 2026-11-22 · `72eda40`
- Calls panel keeps its text and buttons inside the frame.
- The Ear (microphone) meter moved under the gauges and glows while Sebas listens.
- README: troubleshooting for calls stuck in speaker mode (VB-Cable *CABLE In 16ch* and FxSound).

### v1.10.3 · 2026-11-19 · `a6fb0fe`
- `LICENSE` file added: MIT for Sebas.
- OpenJarvis in `sebas_main/` noted as Apache 2.0.

### v1.10.2 · 2026-11-19 · `7415971`
- README reformatted for reading: contents list, collapsible sections, tables.
- Version history added to README and FEATURES.md.

### v1.10.1 · 2026-11-17 · `ac40977`
- **FEATURES.md**: every feature on one page, what to say, and which ones use Gemini.

### v1.10.0 · 2026-11-16 · `0353d89`
- **Your day**: screen-time diary and limits, "what did I do today?", bedtime wind-down.
- **Search my stuff** across notes, Documents, journal and flashcards.
- **Claude reviews your pull requests** (read-only).

### v1.9.0 · 2026-11-16 · `6646cf8`
- **Messages**: WhatsApp, Gmail compose and your Discord server, always behind a yes.
- **Browser hands**: Sebas works in a tab of your own Edge through a small extension.

### v1.8.0 · 2026-11-15 · `93011cd`
- **Errands**: several steps from one request, run in the background as a checklist.
- Gemini or the local model chosen by the "quarter of today's budget" rule.

### v1.7.0 · 2026-11-15 · `3f7663d`
- **Standing orders and watches** ("tell me when the deploy finishes", weekday routines).
- **Coding delegate** (Claude Code on its own branch, Antigravity fallback), **file hands** and **desk hands**.
- The **yes-gate** for risky actions, with an action log.

### v1.6.1 · 2026-11-12 · `aa12c93`
- Call audio pipeline: hearing callers and speaking over calls (clean mode).

### v1.6.0 · 2026-11-12 · `1282561`
- **Sebas on your calls**: takes calls, passes on messages, captions.
- **Voice on Discord**: voice notes and the Sebas Voice channel.
- Interface improvements.

### v1.5.1 · 2026-11-08 · `ede55dc`
- Agenda: no duplicate tasks, and "mark everything as done".

### v1.5.0 · 2026-11-08 · `3ad9ac1`
- **Study mode** (Pomodoro, flashcards, quizzes, exams) and the **wellbeing butler**.
- **Games Room** and **web search**.
- First offline tests (`run.bat --selftest`).

### v1.4.0 · 2026-11-07 · `6147073`
- **Gemini** becomes the brain, with the key and model ladder; the **Discord bot**; the **proactive butler** (briefings, check-ins, alerts).
- Agenda, expenses and journal; music, system settings, screen, clipboard and Downloads tidy; reading aloud and lecture notes.
- **AniList**, **Easter eggs**, and the Sebas avatar.

### v1.3.0 · 2026-11-06 · `f506a77`
- **Desktop interface** ("Brass & Hologram").
- Conversation follow-up mode and live events to the interface.

### v1.2.0 · 2026-11-06 · `51faafb`
- **Local Ollama model** fallback and offline mode.

### v1.1.1 · 2026-11-06 · `6d9f096`
- README: conversation mode, memory tool and follow-up setting.

### v1.1.0 · 2026-11-06 · `0d7d721`
- **The complete codebase**: voice pipeline (wake on "Sebas", faster-whisper, Kokoro) on OpenJarvis.
- DevOps, GitHub, Steam, Bookswagon, morning briefing and laptop tools; `run.bat`.

### v1.0.1 · 2026-11-06 · `c1f2252`
- First full README.

### v1.0.0 · 2026-11-06 · `90d329c`
- First commit.

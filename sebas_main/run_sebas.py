"""Run Sebas: "Sebas" -> speech recognition -> orchestrator -> speech output.

    python run_sebas.py             Voice mode: "Sebas, rise" or "Sebas, <request>"
    python run_sebas.py --text      Type instead of speaking; prints the replies
    python run_sebas.py --mic-test  Measure microphone levels and suggest a threshold
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from sebas_bootstrap import load_env

load_env()  # Must run before anything imports openjarvis.

from sebas_brain import Brain  # noqa: E402  (Claude, or a local model offline)

logger = logging.getLogger("sebas")

_FAILURE_REPLY = (
    "I regret to report that the request could not be completed. "
    "The details are in the console, should you wish to review them."
)


_SUMMON_REPLY = "At your service."


def run_voice_turn(listener, ears, mouth, brain, follow_up_seconds: float = 0.0) -> None:
    """Handle one conversation, from "Sebas" until the user stops talking.

    "Sebas, rise" is answered and followed by a request; "Sebas, <request>"
    is handled directly. With ``follow_up_seconds`` above zero, Sebas keeps
    listening after each reply, so follow-ups need no "Sebas".
    """
    from voice_pipeline.name_listener import is_summon, request_text, split_address

    print('Listening for "Sebas"...', flush=True)
    pcm, remainder = listener.wait()
    if is_summon(remainder):
        mouth.speak(_SUMMON_REPLY)
        mouth.chime()
        text = ears.listen(wait_seconds=max(follow_up_seconds, 6.0))
    else:
        # The quick model only decides whether Sebas was addressed; the
        # accurate model re-reads the same audio for the request itself.
        accurate = split_address(ears.transcribe(pcm))
        text = request_text(accurate if accurate else remainder)

    while text:
        print(f"You:   {text}", flush=True)
        try:
            reply = brain.ask(text)
        except Exception:
            logger.exception("The request failed")
            reply = _FAILURE_REPLY
        print(f"Sebas: {reply}", flush=True)
        try:
            mouth.speak(reply)
        except Exception:
            logger.exception("Speech output failed")
        if follow_up_seconds <= 0:
            return
        mouth.chime()  # still listening
        text = ears.listen(wait_seconds=follow_up_seconds)


def run_voice(brain) -> None:
    from voice_pipeline.ears import Ears
    from voice_pipeline.mouth import Mouth
    from voice_pipeline.name_listener import NameListener

    print("Loading voice models...", flush=True)
    threshold = int(os.environ.get("SEBAS_SILENCE_THRESHOLD") or 500)
    quick_ears = Ears(os.environ.get("SEBAS_NAME_MODEL") or "tiny.en", threshold)
    quick_ears.load()
    ears = Ears(os.environ.get("SEBAS_WHISPER_MODEL") or "small.en", threshold)
    ears.load()
    listener = NameListener(quick_ears, threshold)
    mouth = Mouth(voice=os.environ.get("SEBAS_VOICE") or "bm_george")
    mouth.load()

    from custom_tools.laptop import set_announcer

    def announce(text: str) -> None:
        print(f"\nSebas: {text}", flush=True)
        mouth.speak(text)

    set_announcer(announce)
    follow_up = float(os.environ.get("SEBAS_FOLLOW_UP_SECONDS") or 8)
    print('Ready. Say "Sebas, rise", or "Sebas" followed by a request.', flush=True)
    while True:
        run_voice_turn(listener, ears, mouth, brain, follow_up)


def run_text(brain) -> None:
    from custom_tools.laptop import set_announcer

    set_announcer(lambda text: print(f"\nSebas: {text}\nYou:   ", end="", flush=True))
    while True:
        text = input("You:   ").strip()
        if not text:
            continue
        try:
            print(f"Sebas: {brain.ask(text)}")
        except Exception:
            logger.exception("The request failed")
            print(f"Sebas: {_FAILURE_REPLY}")


def mic_test(seconds: int = 6) -> None:
    import numpy as np
    import sounddevice as sd

    rate = 16000
    print(f"Recording for {seconds} seconds. Stay quiet for 3, then speak normally.")
    audio = sd.rec(seconds * rate, samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    samples = audio[:, 0].astype(np.float64)
    frames = samples[: samples.size - samples.size % 1024].reshape(-1, 1024)
    levels = np.sqrt(np.mean(frames**2, axis=1))
    noise = float(np.median(levels[: levels.size // 2]))
    speech = float(levels[levels.size // 2 :].max())
    print(f"Background level: {noise:.0f}")
    print(f"Speech peak:      {speech:.0f}")
    if speech < noise * 2:
        print("Speech is barely louder than the background. Check the microphone.")
    else:
        print(f"Suggested .env setting: SEBAS_SILENCE_THRESHOLD={(noise + speech) / 2:.0f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Sebas voice assistant.")
    parser.add_argument("--text", action="store_true", help="type instead of speaking")
    parser.add_argument(
        "--mic-test", action="store_true", help="measure microphone levels and exit"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    if args.mic_test:
        mic_test()
        return 0
    try:
        brain = Brain()
    except RuntimeError as exc:
        print(f"Sebas cannot start: {exc}")
        print("Add ANTHROPIC_API_KEY to .env, or install a local model with Ollama.")
        return 1
    print(f"Thinking with {brain.description}.", flush=True)
    try:
        run_text(brain) if args.text else run_voice(brain)
    except (KeyboardInterrupt, EOFError):
        print("\nVery good. Sebas is retiring for now.")
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

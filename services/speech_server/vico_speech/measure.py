"""Measure real latency on the machine the speech server runs on.

    python -m vico_speech.measure --wav sample.wav [--runs 5] [--voice]

Prints load time, transcription latency (mean and worst) and real-time factor, and, with
--voice, synthesis latency per language. Run it on the actual server (e.g. the Oracle
Ampere instance); numbers from another machine do not describe that server.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import time
from pathlib import Path

from vico_speech.engines import SAMPLE_RATE, decode_wav

PHRASES = {
    "en": "Your folder has been created.",
    "yo": "Mo ti ṣẹ̀dá fóldà rẹ.",
    "ha": "Na ƙirƙiri babban fayil ɗinka.",
    "ig": "Emepụtala m folda gị.",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path, required=True, help="16 kHz mono 16-bit WAV")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--models", type=Path, default=Path(os.environ.get("VICO_SPEECH_MODELS", "models")))
    args = parser.parse_args()

    print(f"machine: {platform.machine()} · {os.cpu_count()} CPUs · {platform.platform()}")
    samples = decode_wav(args.wav.read_bytes())
    seconds = samples.size / SAMPLE_RATE

    from vico_speech.engines import OmnilingualRecognizer

    t0 = time.perf_counter()
    recognizer = OmnilingualRecognizer(args.models)
    print(f"ASR load: {time.perf_counter() - t0:.1f} s")
    timings = []
    for i in range(args.runs):
        t = time.perf_counter()
        text = recognizer.transcribe(samples, None)
        timings.append(time.perf_counter() - t)
        if i == 0:
            print(f"transcript: {text}")
    mean = statistics.mean(timings)
    print(f"ASR on {seconds:.1f} s of audio: mean {mean:.2f} s, worst {max(timings):.2f} s, "
          f"real-time factor {mean / seconds:.2f}")

    if args.voice:
        from vico_speech.engines import YarnVoice

        t0 = time.perf_counter()
        voice = YarnVoice(args.models, Path(os.environ.get("VICO_YARNGPT_CODE", "yarngpt")))
        print(f"voice load: {time.perf_counter() - t0:.1f} s")
        for lang, phrase in PHRASES.items():
            t = time.perf_counter()
            audio, rate = voice.speak(phrase, lang)
            took = time.perf_counter() - t
            length = audio.size / rate
            print(f"voice {lang}: {took:.2f} s for {length:.2f} s of speech (real-time factor {took / length:.2f})")


if __name__ == "__main__":
    main()

"""Measure real speech accuracy and correct-command rate per language, from consented recordings.

1. Record short WAV clips (16 kHz mono 16-bit) from willing speakers, with their consent,
   into tests/language_samples/ (kept out of git).
2. List them in tests/language_samples/manifest.json, e.g.
   [{"file": "yo_01.wav", "language": "yo", "expected_text": "Ṣẹ̀dá fóldà Demo",
     "expected_tool": "create_folder", "consent": true}]
3. Choose the speech provider to measure and (optionally) the planner used for the
   correct-command check, then run from services/agent:

     uv run python ../../scripts/benchmark_languages.py --stt gemini --planner gemini
     uv run python ../../scripts/benchmark_languages.py --stt omnilingual --planner gemini
     uv run python ../../scripts/benchmark_languages.py --stt groq --planner none

   Keys come from the credential store or VICO_GEMINI_API_KEY / VICO_GROQ_API_KEY.
   The Omnilingual speech server needs VICO_SPEECH_SERVER_URL and VICO_SPEECH_SERVER_TOKEN
   (or the address and token saved in Vico's settings).

Metrics, per language:
  - WER: word error rate against expected_text (lower is better)
  - CER: character error rate, diacritics kept (tone-mark mistakes count)
  - command rate: share of clips where the planner picked expected_tool
  - latency: median transcription time
Writes tests/language_samples/results-<date>-<stt>.csv and updates language_results.json
in Vico's data folder, which is the only source of the app's language labels. Languages
without measured clips are reported as "not measured"; nothing is estimated.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "agent"))

from app.agent.prompts import PLANNER_SYSTEM, planner_user_prompt  # noqa: E402
from app.agent.schemas import ToolCallPlan, parse_plan  # noqa: E402
from app.config import data_dir  # noqa: E402
from app.providers.base import parse_json_text  # noqa: E402
from app.providers.registry import ProviderHub  # noqa: E402
from app.security.secret_store import SecretStore  # noqa: E402
from app.store.settings import Settings  # noqa: E402
from app.tools import build_registry  # noqa: E402

SAMPLES = ROOT / "tests" / "language_samples"
LANGUAGES = ["en", "yo", "ha", "ig", "pcm"]
NOT_MEASURED = "not measured"


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.casefold())
    return "".join(c if c.isalnum() or c.isspace() or unicodedata.combining(c) else " " for c in text).split()


def edit_distance(ref: list, hyp: list) -> int:
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(hyp)]


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    return (0.0 if not h else 1.0) if not r else edit_distance(r, h) / len(r)


def cer(ref: str, hyp: str) -> float:
    r = list(" ".join(words(ref)))
    h = list(" ".join(words(hyp)))
    return (0.0 if not h else 1.0) if not r else edit_distance(r, h) / len(r)


async def plan_tool(hub: ProviderHub, text: str, tools: list[dict]) -> str:
    understood = await hub.understand(text)
    prompt = planner_user_prompt(original=understood["restored"], canonical=understood["english"],
                                 language=understood["language"], tools=tools, workspace="~/Documents/VicoDemo",
                                 allowed_roots=["~"], steps=[], clarifications=[])
    completion = await hub.complete(PLANNER_SYSTEM, prompt)
    plan = parse_plan(parse_json_text(completion.text))
    return plan.tool if isinstance(plan, ToolCallPlan) else plan.kind


def make_hub(stt: str, planner: str) -> ProviderHub:
    url = os.environ.get("VICO_SPEECH_SERVER_URL")
    token = os.environ.get("VICO_SPEECH_SERVER_TOKEN")
    if token:
        os.environ["VICO_SPEECH_SERVER_API_KEY"] = token  # read by SecretStore as the "speech_server" key
    settings = Settings(cloud_consent=True, stt_provider="gemini" if stt == "omnilingual" else stt,
                        llm_provider=planner if planner != "none" else "gemini",
                        fallback_consent=False, speech_server_url=url)
    hub = ProviderHub(SecretStore(), lambda: settings)
    if stt == "omnilingual":
        provider = hub.provider("omnilingual")
        if provider is None:
            raise SystemExit("Set VICO_SPEECH_SERVER_URL and VICO_SPEECH_SERVER_TOKEN for the Omnilingual server.")
        hub.overrides["gemini"] = provider  # measure only this provider: no fallback to others
    return hub


async def run(stt: str, planner: str, text_only: bool) -> None:
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    hub = make_hub(stt, planner)
    tools = [t.manifest() for t in build_registry().available(sys.platform, online=True)]
    rows: list[dict] = []
    for sample in manifest:
        if not sample.get("consent"):
            print(f"skip {sample.get('file')}: no recorded consent")
            continue
        audio_path = SAMPLES / sample["file"] if sample.get("file") else None
        speech = not text_only and audio_path is not None and audio_path.is_file()
        row = {"file": sample.get("file", ""), "language": sample["language"], "mode": "speech" if speech else "text",
               "stt": stt if speech else "", "expected_text": sample["expected_text"],
               "expected_tool": sample.get("expected_tool", "")}
        try:
            if speech:
                started = time.perf_counter()
                transcript = await hub.transcribe(audio_path.read_bytes(), "audio/wav", sample["language"])
                row.update(transcript=transcript.text, latency_ms=int((time.perf_counter() - started) * 1000),
                           wer=round(wer(sample["expected_text"], transcript.text), 3),
                           cer=round(cer(sample["expected_text"], transcript.text), 3))
            else:
                row.update(transcript=sample["expected_text"])
            if planner != "none" and row["expected_tool"]:
                row["tool"] = await plan_tool(hub, row["transcript"], tools)
                row["command_ok"] = row["tool"] == row["expected_tool"]
        except Exception as exc:  # failures are recorded, never hidden
            row.update(error=str(exc)[:200], command_ok=False if planner != "none" else "")
        rows.append(row)
        print(row)
    await hub.aclose()

    out = SAMPLES / f"results-{date.today()}-{stt}.csv"
    fields = sorted({k for r in rows for k in r})
    if rows:
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    results_path = data_dir() / "language_results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        results = {}

    print(f"\nSummary (speech: {stt}, planner: {planner})")
    print(f"{'lang':5} {'clips':>5} {'WER':>14} {'CER':>14} {'command rate':>14} {'latency p50':>14}")
    for lang in LANGUAGES:
        speech_rows = [r for r in rows if r["language"] == lang and r["mode"] == "speech" and "wer" in r]
        text_rows = [r for r in rows if r["language"] == lang and r["mode"] == "text"]
        judged = [r for r in rows if r["language"] == lang and isinstance(r.get("command_ok"), bool)]

        def fmt(values: list[float], pct: bool = False) -> str:
            if not values:
                return NOT_MEASURED
            v = statistics.mean(values)
            return f"{v:.0%}" if pct else f"{v:.2f}"

        rate = [1.0 if r["command_ok"] else 0.0 for r in judged]
        latency = [r["latency_ms"] for r in speech_rows]
        print(f"{lang:5} {len(speech_rows):>5} {fmt([r['wer'] for r in speech_rows]):>14} "
              f"{fmt([r['cer'] for r in speech_rows]):>14} {fmt(rate, pct=True):>14} "
              f"{(str(int(statistics.median(latency))) + ' ms') if latency else NOT_MEASURED:>14}")

        entry = results.setdefault(lang, {})
        if speech_rows:
            speech_judged = [r for r in judged if r["mode"] == "speech"]
            entry.setdefault("speech_by_provider", {})[stt] = {
                "samples": len(speech_rows),
                "wer": round(statistics.mean(r["wer"] for r in speech_rows), 3),
                "cer": round(statistics.mean(r["cer"] for r in speech_rows), 3),
                "intent_accuracy": (round(sum(r["command_ok"] for r in speech_judged) / len(speech_judged), 3)
                                    if speech_judged else None),
                "date": str(date.today()),
            }
            # The app label uses the best measured provider for this language.
            best = max(entry["speech_by_provider"].values(),
                       key=lambda m: (m["intent_accuracy"] or 0, -m["wer"]))
            entry["speech"] = {"samples": best["samples"], "intent_accuracy": best["intent_accuracy"]}
        text_judged = [r for r in judged if r["mode"] == "text"]
        if text_rows and text_judged:
            entry["text"] = {"samples": len(text_judged),
                             "intent_accuracy": round(sum(r["command_ok"] for r in text_judged) / len(text_judged), 3),
                             "planner": planner, "date": str(date.today())}
    results = {k: v for k, v in results.items() if v}
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out if rows else '(no rows)'} and {results_path}")


if __name__ == "__main__":
    # Windows consoles default to a legacy code page that cannot show Yoruba, Hausa or Igbo letters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--stt", choices=["gemini", "omnilingual", "groq"], default="gemini")
    parser.add_argument("--planner", choices=["gemini", "groq", "none"], default="gemini")
    parser.add_argument("--text-only", action="store_true", help="skip audio; test typed commands only")
    args = parser.parse_args()
    asyncio.run(run(args.stt, args.planner, args.text_only))

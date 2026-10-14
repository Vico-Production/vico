"""Measure real transcription and intent accuracy per language, from consented recordings.

1. Record short WAV clips (16 kHz mono) from willing speakers, with their consent.
2. List them in tests/language_samples/manifest.json, e.g.
   [{"file": "yo_01.wav", "language": "yo", "expected_text": "Ṣẹ̀dá fóldà Demo",
     "expected_tool": "create_folder", "consent": true}]
3. Set an API key (VICO_GROQ_API_KEY or VICO_GEMINI_API_KEY) and run:
     cd services/agent && uv run python ../../scripts/benchmark_languages.py --provider groq

Writes tests/language_samples/results-<date>.csv and updates language_results.json in
Vico's data folder, which the app uses for its speech/text labels. Nothing is invented:
languages with no measured samples stay 'untested'.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
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


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.casefold())
    return "".join(c if c.isalnum() or c.isspace() else " " for c in text).split()


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)


async def intent(hub: ProviderHub, text: str, language: str, tools: list[dict]) -> str | None:
    canonical = text if language == "en" else (await hub.translate(text, language, "en"))["text"]
    prompt = planner_user_prompt(original=text, canonical=canonical, language=language, tools=tools,
                                 workspace="~/Documents/VicoDemo", allowed_roots=["~"], steps=[], clarifications=[])
    completion = await hub.complete(PLANNER_SYSTEM, prompt)
    plan = parse_plan(parse_json_text(completion.text))
    return plan.tool if isinstance(plan, ToolCallPlan) else plan.kind


async def run(provider: str, text_only: bool) -> None:
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    settings = Settings(cloud_consent=True, stt_provider=provider, llm_provider=provider)
    hub = ProviderHub(SecretStore(), lambda: settings)
    tools = [t.manifest() for t in build_registry().available(sys.platform, online=True)]
    rows = []
    for sample in manifest:
        if not sample.get("consent"):
            print(f"skip {sample.get('file')}: no recorded consent")
            continue
        lang = sample["language"]
        row = {"file": sample.get("file", ""), "language": lang, "mode": "text" if text_only else "speech",
               "expected_text": sample["expected_text"], "expected_tool": sample.get("expected_tool", "")}
        try:
            if text_only or not sample.get("file"):
                row.update(mode="text", transcript=sample["expected_text"], latency_ms=0, wer="")
            else:
                audio = (SAMPLES / sample["file"]).read_bytes()
                t = await hub.transcribe(audio, "audio/wav", lang)
                row.update(transcript=t.text, latency_ms=t.latency_ms, wer=round(wer(sample["expected_text"], t.text), 3))
            row["tool"] = await intent(hub, row["transcript"], lang, tools)
            row["intent_ok"] = row["tool"] == row["expected_tool"]
        except Exception as exc:  # record failures honestly
            row.update(error=str(exc)[:200], intent_ok=False)
        rows.append(row)
        print(row)
    await hub.aclose()

    out = SAMPLES / f"results-{date.today()}-{provider}.csv"
    fields = sorted({k for r in rows for k in r})
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    results_path = data_dir() / "language_results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        results = {}
    for lang in {r["language"] for r in rows}:
        for mode in ("text", "speech"):
            subset = [r for r in rows if r["language"] == lang and r["mode"] == mode]
            if subset:
                results.setdefault(lang, {})[mode] = {
                    "samples": len(subset),
                    "intent_accuracy": round(sum(bool(r.get("intent_ok")) for r in subset) / len(subset), 3),
                    "provider": provider, "date": str(date.today()),
                }
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {out} and {results_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["groq", "gemini"], default="groq")
    parser.add_argument("--text-only", action="store_true", help="skip audio; test typed intent only")
    args = parser.parse_args()
    asyncio.run(run(args.provider, args.text_only))

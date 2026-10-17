"""An offline English voice: Kokoro-82M (Apache-2.0), run with ONNX Runtime (MIT).

No GPL code: words are turned into Kokoro's phonemes with the pronunciation dictionaries of
misaki (Apache-2.0, Kokoro's own G2P), read directly; words the dictionaries don't know are
spelled from letter sounds. (misaki's full English mode and kokoro-onnx would pull in
espeak-ng, which is GPL-3.0.)

The model (88 MB, int8) and voices (28 MB) are downloaded once, the first time they are
needed, from the kokoro-onnx project's release, and used only if their SHA-256 matches.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app.config import data_dir

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {  # name: (size, sha256), checked 2026-10-17
    "kokoro-v1.0.int8.onnx": (92_361_271, "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
    "voices-v1.0.bin": (28_214_398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}
VOICE = "af_heart"
RATE = 24_000
MAX_TOKENS = 500

# Kokoro v1.0's phoneme vocabulary (from kokoro-onnx's config.json, MIT).
VOCAB = {
    ";": 1, ":": 2, ",": 3, ".": 4, "!": 5, "?": 6, "—": 9, "…": 10, '"': 11, "(": 12, ")": 13, "“": 14, "”": 15,
    " ": 16, "̃": 17, "ʣ": 18, "ʥ": 19, "ʦ": 20, "ʨ": 21, "ᵝ": 22, "ꭧ": 23, "A": 24, "I": 25, "O": 31,
    "Q": 33, "S": 35, "T": 36, "W": 39, "Y": 41, "ᵊ": 42, "a": 43, "b": 44, "c": 45, "d": 46, "e": 47, "f": 48,
    "h": 50, "i": 51, "j": 52, "k": 53, "l": 54, "m": 55, "n": 56, "o": 57, "p": 58, "q": 59, "r": 60, "s": 61,
    "t": 62, "u": 63, "v": 64, "w": 65, "x": 66, "y": 67, "z": 68, "ɑ": 69, "ɐ": 70, "ɒ": 71, "æ": 72, "β": 75,
    "ɔ": 76, "ɕ": 77, "ç": 78, "ɖ": 80, "ð": 81, "ʤ": 82, "ə": 83, "ɚ": 85, "ɛ": 86, "ɜ": 87, "ɟ": 90, "ɡ": 92,
    "ɥ": 99, "ɨ": 101, "ɪ": 102, "ʝ": 103, "ɯ": 110, "ɰ": 111, "ŋ": 112, "ɳ": 113, "ɲ": 114, "ɴ": 115, "ø": 116,
    "ɸ": 118, "θ": 119, "œ": 120, "ɹ": 123, "ɾ": 125, "ɻ": 126, "ʁ": 128, "ɽ": 129, "ʂ": 130, "ʃ": 131, "ʈ": 132,
    "ʧ": 133, "ʊ": 135, "ʋ": 136, "ʌ": 138, "ɣ": 139, "ɤ": 140, "χ": 142, "ʎ": 143, "ʒ": 147, "ʔ": 148, "ˈ": 156,
    "ˌ": 157, "ː": 158, "ʰ": 162, "ʲ": 164, "↓": 169, "→": 171, "↗": 172, "↘": 173, "ᵻ": 177,
}
# Words the dictionaries don't have that Vico says often.
OWN_WORDS = {"Vico": "vˈikO", "vico": "vˈikO", "Vico's": "vˈikOz", "WhatsApp": "wˈʌtsˌæp", "CapCut": "kˈæpkˌʌt",
             "Groq": "ɡɹˈɑk", "Gemini": "ʤˈɛmənˌI", "Naija": "nˈIʤə", "wetin": "wˈɛtɪn", "abeg": "ˈɑbɛɡ"}
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + number_words(rest))
    for size, word in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if n >= size:
            rest = n % size
            return number_words(n // size) + f" {word}" + ("" if rest == 0 else " " + number_words(rest))
    return str(n)


class Lexicon:
    """misaki's US English pronunciation dictionaries (gold first, then silver)."""

    def __init__(self) -> None:
        import misaki

        data = Path(misaki.__file__).parent / "data"
        self.words: dict[str, Any] = {}
        for name in ("us_silver.json", "us_gold.json"):  # gold last: it wins
            self.words.update(json.loads((data / name).read_text(encoding="utf-8")))
        self.words.update(OWN_WORDS)

    def word(self, w: str) -> str:
        for key in (w, w.lower(), w.capitalize()):
            found = self.words.get(key)
            if isinstance(found, dict):
                found = found.get("DEFAULT") or next(iter(found.values()), None)
            if isinstance(found, str):
                return found
        if w.lower().endswith("'s") and len(w) > 2:
            base = self.word(w[:-2])
            return base + "z" if base else ""
        # Unknown (names, slang): letter by letter for short ones, else by letter sounds.
        if len(w) <= 4 and w.isalpha():
            return " ".join(self.word(c.upper()) or "" for c in w)
        return "".join(self.words.get(c, "") if isinstance(self.words.get(c), str) else c for c in w.lower())

    def phonemes(self, text: str) -> str:
        out: list[str] = []
        for token in re.findall(r"\d+|[A-Za-z']+|[.,!?;:—…]", text):
            if token.isdigit():
                out.extend(self.word(w) for w in number_words(int(token)).split())
            elif token[0].isalpha() or token[0] == "'":
                out.append(self.word(token))
            elif out:
                out[-1] += token
        return " ".join(p for p in out if p)


def model_dir() -> Path:
    return data_dir() / "models" / "kokoro"


def ensure_files(directory: Path, fetch: Any = None) -> None:
    """Download the model and voices once (in memory, then written), keeping them only if the
    SHA-256 matches."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        path = directory / name
        if path.is_file() and path.stat().st_size == size:
            continue
        if fetch is None:
            import httpx

            def fetch(url: str) -> bytes:
                with httpx.Client(follow_redirects=True, timeout=300) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    return r.content

        data = fetch(RELEASE + name)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"{name} did not match its checksum; it was not kept")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)


class KokoroVoice:
    """Loaded on first use and kept in memory, so later replies start quickly."""

    def __init__(self, directory: Path | None = None):
        import onnxruntime as ort

        directory = directory or model_dir()
        ensure_files(directory)
        options = ort.SessionOptions()
        self.session = ort.InferenceSession(str(directory / "kokoro-v1.0.int8.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.style = np.load(directory / "voices-v1.0.bin")[VOICE]
        self.lexicon = Lexicon()
        self._lock = threading.Lock()

    def speak(self, text: str) -> bytes:
        """WAV bytes (24 kHz) for English text."""
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
        pieces: list[np.ndarray] = []
        for sentence in sentences or [text]:
            phonemes = self.lexicon.phonemes(sentence)
            ids = [VOCAB[c] for c in phonemes if c in VOCAB][:MAX_TOKENS]
            if not ids:
                continue
            with self._lock:
                audio = self.session.run(None, {
                    "tokens": np.array([[0, *ids, 0]], dtype=np.int64),
                    "style": self.style[len(ids)].astype(np.float32),
                    "speed": np.ones(1, dtype=np.float32),
                })[0]
            pieces.append(audio.astype(np.float32))
            pieces.append(np.zeros(int(RATE * 0.15), dtype=np.float32))  # a short breath between sentences
        if not pieces:
            raise ValueError("Nothing to say.")
        samples = np.clip(np.concatenate(pieces), -1.0, 1.0)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((samples * 32767).astype("<i2").tobytes())
        return out.getvalue()


_voice: KokoroVoice | None = None
_voice_lock = threading.Lock()


def speak(text: str) -> bytes | None:
    """Offline English speech from Kokoro, or None if it cannot be prepared (no download yet and
    no internet, or the files did not match)."""
    global _voice
    try:
        with _voice_lock:
            if _voice is None:
                _voice = KokoroVoice()
        return _voice.speak(text)
    except Exception:  # noqa: BLE001 - the next voice in line is used instead
        return None


def prepare_in_background() -> None:
    """Download (once) and load the voice ahead of the first spoken reply."""
    def load() -> None:
        global _voice
        try:
            with _voice_lock:
                if _voice is None:
                    _voice = KokoroVoice()
        except Exception:  # noqa: BLE001, S110 - it is only a head start
            pass

    threading.Thread(target=load, name="vico-kokoro-load", daemon=True).start()

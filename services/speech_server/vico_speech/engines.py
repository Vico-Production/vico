"""Speech engines. Heavy libraries are imported only when an engine is created, so the
HTTP layer and its tests do not need them."""

from __future__ import annotations

import io
import os
import sys
import threading
import wave
from pathlib import Path
from typing import Protocol

import numpy as np

from vico_speech.artifacts import (
    NAIJAVOX_ARTIFACTS,
    OMNI_CTC_300M,
    OMNI_TOKENIZER,
    WAVTOKENIZER_CKPT,
    WAVTOKENIZER_CONFIG,
    YARN_MODEL,
    fetch,
)

SAMPLE_RATE = 16_000
MAX_SECONDS = 40.0  # Omnilingual CTC/LLM models accept audio shorter than 40 s


class BadAudio(ValueError):
    pass


def decode_wav(data: bytes) -> np.ndarray:
    """16 kHz mono 16-bit WAV bytes -> float32 samples in [-1, 1]. Never touches disk."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE:
                raise BadAudio("Send 16 kHz mono 16-bit WAV audio.")
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise BadAudio("The audio is not a readable WAV file.") from exc
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size / SAMPLE_RATE > MAX_SECONDS:
        raise BadAudio(f"Audio longer than {MAX_SECONDS:.0f} s is not accepted.")
    if samples.size < SAMPLE_RATE // 10:
        raise BadAudio("The audio is too short.")
    return samples


def encode_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Recognizer(Protocol):
    model: str

    def transcribe(self, samples: np.ndarray, language: str | None) -> str: ...


class Voice(Protocol):
    model: str
    languages: tuple[str, ...]

    def speak(self, text: str, language: str) -> tuple[np.ndarray, int]: ...


# fairseq2 asset card pointing Meta's pipeline at the files we downloaded and verified,
# in the same format as omnilingual_asr/cards/models/rc_models_v1.yaml.
ASSET_CARD = """name: vico_omniASR_tokenizer
tokenizer_family: char_tokenizer
tokenizer: {tokenizer}
---
name: vico_omniASR_CTC_300M
model_family: wav2vec2_asr
model_arch: 300m
checkpoint: {checkpoint}
tokenizer_ref: vico_omniASR_tokenizer
"""


class OmnilingualRecognizer:
    """Meta Omnilingual ASR, CTC 300M. CTC models need no language hint: they transcribe
    whatever is spoken, so Yoruba, Hausa, Igbo and English all go through one model."""

    model = "omniASR_CTC_300M"

    def __init__(self, models_dir: Path):
        checkpoint = fetch(OMNI_CTC_300M, models_dir)
        tokenizer = fetch(OMNI_TOKENIZER, models_dir)
        card = ASSET_CARD.format(checkpoint=checkpoint.as_uri(), tokenizer=tokenizer.as_uri())
        # fairseq2 reads user asset cards from FAIRSEQ2_USER_ASSET_DIR or ~/.config/fairseq2/assets.
        card_dir = models_dir / "fairseq2-assets"
        user_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "fairseq2" / "assets"
        for directory in (card_dir, user_dir):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "vico.yaml").write_text(card, encoding="utf-8")
        os.environ.setdefault("FAIRSEQ2_USER_ASSET_DIR", str(card_dir))
        from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline

        self.pipeline = ASRInferencePipeline(model_card="vico_omniASR_CTC_300M")
        self._lock = threading.Lock()

    def transcribe(self, samples: np.ndarray, language: str | None) -> str:
        with self._lock:
            result = self.pipeline.transcribe([{"waveform": samples, "sample_rate": SAMPLE_RATE}], batch_size=1)
        return str(result[0]).strip()


# NaijaVox language tokens (from its model card; Igbo and Pidgin are tokens it added).
NAIJAVOX_LANGUAGES = {"yo": "<|yo|>", "ha": "<|ha|>", "ig": "<|ig|>", "pcm": "<|pcm|>", "en": "<|en|>"}


class NaijaVoxRecognizer:
    """NaijaVox-2.0: Whisper large-v3 fine-tuned on Nigerian speech. Told the language when
    Vico knows it; otherwise Whisper detects it. Runs on a GPU when there is one."""

    model = "NaijaVox-2.0"

    def __init__(self, models_dir: Path):
        model_dir = models_dir / "NaijaVox-2.0"
        for artifact in NAIJAVOX_ARTIFACTS:
            fetch(artifact, model_dir)
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.processor = WhisperProcessor.from_pretrained(str(model_dir))
        self.net = WhisperForConditionalGeneration.from_pretrained(str(model_dir), torch_dtype=dtype).to(self.device)
        self.net.eval()
        self.dtype = dtype
        self._lock = threading.Lock()

    def transcribe(self, samples: np.ndarray, language: str | None) -> str:
        import torch

        features = self.processor(samples, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
        features = features.to(self.device, dtype=self.dtype)
        kwargs: dict = {"max_new_tokens": 440, "num_beams": 1}
        token = NAIJAVOX_LANGUAGES.get(language or "")
        if token:
            tid = self.processor.tokenizer.convert_tokens_to_ids(token)
            start = self.processor.tokenizer.convert_tokens_to_ids("<|startoftranscript|>")
            task = self.processor.tokenizer.convert_tokens_to_ids("<|transcribe|>")
            notime = self.processor.tokenizer.convert_tokens_to_ids("<|notimestamps|>")
            kwargs["decoder_input_ids"] = torch.tensor([[start, tid, task, notime]], device=self.device)
        with self._lock, torch.inference_mode():
            ids = self.net.generate(features, **kwargs)
        return str(self.processor.batch_decode(ids, skip_special_tokens=True)[0]).strip()


# YarnGPT voice names, from the model card ("arranged in order of performance and stability").
YARN_LANGUAGES = {"en": "english", "yo": "yoruba", "ig": "igbo", "ha": "hausa"}
YARN_VOICES = {"en": "idera", "yo": "yoruba_male2", "ig": "igbo_female2", "ha": "hausa_female1"}


class YarnVoice:
    """YarnGPT2b: Nigerian voices for English, Yoruba, Igbo and Hausa (24 kHz)."""

    model = "YarnGPT2b"
    languages = tuple(YARN_LANGUAGES)

    def __init__(self, models_dir: Path, code_dir: Path):
        from huggingface_hub import snapshot_download

        model_dir = models_dir / "YarnGPT2b"
        # Tokenizer and config files at the pinned commit; the weights are verified by SHA-256.
        snapshot_download(repo_id=YARN_MODEL.repo, revision=YARN_MODEL.revision, local_dir=model_dir,
                          allow_patterns=["*.json", "merges.txt", "vocab.json"])
        fetch(YARN_MODEL, model_dir)
        checkpoint = fetch(WAVTOKENIZER_CKPT, models_dir)
        config = fetch(WAVTOKENIZER_CONFIG, models_dir)
        sys.path.insert(0, str(code_dir))
        from audiotokenizer import AudioTokenizerV2  # type: ignore[import-not-found]
        from transformers import AutoModelForCausalLM

        self.tokenizer = AudioTokenizerV2(str(model_dir), str(checkpoint), str(config))
        self.lm = AutoModelForCausalLM.from_pretrained(str(model_dir), torch_dtype="auto").to(self.tokenizer.device)
        self._lock = threading.Lock()

    def speak(self, text: str, language: str) -> tuple[np.ndarray, int]:
        lang = YARN_LANGUAGES[language]
        with self._lock:
            prompt = self.tokenizer.create_prompt(text, lang=lang, speaker_name=YARN_VOICES[language])
            input_ids = self.tokenizer.tokenize_prompt(prompt)
            output = self.lm.generate(input_ids=input_ids, temperature=0.1, repetition_penalty=1.1, max_length=4000)
            audio = self.tokenizer.get_audio(self.tokenizer.get_codes(output))
        return audio.squeeze().detach().cpu().numpy().astype(np.float32), 24_000

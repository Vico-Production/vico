"""Push-to-talk microphone capture.

Audio is kept in memory only (never written to disk), capped at 15 seconds, and the
stream is closed on stop, cancel, timeout and app shutdown.
"""

from __future__ import annotations

import array
import io
import math
import threading
import time
import wave
from collections.abc import Callable
from typing import Any

from app.config import MAX_RECORDING_SECONDS
from app.contracts import ErrorCode, VicoError

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16
MIN_SECONDS = 0.4


def to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def rms_level(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    samples = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return 0.0
    mean = sum(s * s for s in samples) / len(samples)
    return min(1.0, math.sqrt(mean) / 8000)


StreamFactory = Callable[[Callable[[bytes], None]], Any]


def _default_stream(callback: Callable[[bytes], None]) -> Any:
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise VicoError(ErrorCode.MIC_UNAVAILABLE, "Audio support is not installed on this computer.") from exc

    def on_audio(indata, frames, time_info, status):  # noqa: ARG001 - sounddevice signature
        callback(bytes(indata))

    try:
        stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16", callback=on_audio)
        stream.start()
        return stream
    except Exception as exc:
        raise VicoError(ErrorCode.MIC_UNAVAILABLE,
                        "No microphone could be opened. Check it is plugged in and that Vico may use it.",
                        status=409) from exc


class Recorder:
    def __init__(self, stream_factory: StreamFactory | None = None, max_seconds: float = MAX_RECORDING_SECONDS):
        self._factory = stream_factory or _default_stream
        self.max_seconds = max_seconds
        self._lock = threading.Lock()
        self._stream: Any = None
        self._chunks: list[bytes] = []
        self._bytes = 0
        self._started = 0.0
        self.language: str | None = None
        self.level = 0.0

    @property
    def active(self) -> bool:
        return self._stream is not None

    @property
    def max_bytes(self) -> int:
        return int(self.max_seconds * SAMPLE_RATE * SAMPLE_WIDTH)

    def _on_audio(self, data: bytes) -> None:
        with self._lock:
            if self._bytes >= self.max_bytes:
                return
            data = data[: self.max_bytes - self._bytes]
            self._chunks.append(data)
            self._bytes += len(data)
            self.level = rms_level(data)

    def start(self, language: str | None) -> None:
        with self._lock:
            if self._stream is not None:
                raise VicoError(ErrorCode.CONFLICT, "Already recording.", status=409)
            self._chunks, self._bytes, self.level = [], 0, 0.0
            self.language = language
        stream = self._factory(self._on_audio)
        with self._lock:
            self._stream = stream
            self._started = time.monotonic()

    def status(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self._started if self.active else 0.0
        return {"recording": self.active, "elapsed_s": round(elapsed, 1), "max_s": self.max_seconds,
                "level": round(self.level, 3), "full": self._bytes >= self.max_bytes}

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: S110 - closing a dead device must not crash shutdown
                pass

    def stop(self) -> tuple[bytes, float]:
        with self._lock:
            if self._stream is None:
                raise VicoError(ErrorCode.CONFLICT, "Not recording.", status=409)
            self._close()
            pcm = b"".join(self._chunks)
            self._chunks, self._bytes, self.level = [], 0, 0.0
        seconds = len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)
        if seconds < MIN_SECONDS:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "That was too short. Hold the button and speak.")
        if rms_level(pcm) < 0.005:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "Vico heard only silence. Check the microphone and try again.")
        return to_wav(pcm), seconds

    def cancel(self) -> None:
        with self._lock:
            self._close()
            self._chunks, self._bytes, self.level = [], 0, 0.0

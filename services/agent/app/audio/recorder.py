"""Push-to-talk microphone capture.

Audio is kept in memory only (never written to disk), capped at 15 seconds, and the
stream is closed on stop, cancel, timeout and app shutdown.

Many laptops ship with a default input that delivers pure digital silence (a muted
array mic, an empty headset jack). When the first half second from a device is exactly
zero, the recorder moves on to the next input by itself and remembers the one that
works for the rest of the session.
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
DEAD_PEAK = 2  # a device whose samples never exceed this is muted or disconnected
PROBE_SECONDS = 1.2  # how long a device may stay dead before the next one is tried
TARGET_PEAK = 24_000  # quiet recordings are raised towards this before transcription
_SKIP_INPUTS = ("stereo mix", "what u hear", "loopback", "sound mapper", "primary sound capture")


def to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _samples(pcm: bytes) -> array.array:
    return array.array("h", pcm[: len(pcm) - len(pcm) % 2])


def peak(pcm: bytes) -> int:
    return max((abs(x) for x in _samples(pcm)), default=0)


def normalize(pcm: bytes) -> bytes:
    """Raise a quiet recording so the speech provider hears it clearly (never lowers it)."""
    samples = _samples(pcm)
    top = max((abs(x) for x in samples), default=0)
    if top <= DEAD_PEAK or top >= TARGET_PEAK:
        return pcm
    gain = min(8.0, TARGET_PEAK / top)
    return array.array("h", (max(-32768, min(32767, int(x * gain))) for x in samples)).tobytes()


def rms_level(pcm: bytes) -> float:
    samples = _samples(pcm)
    if not samples:
        return 0.0
    mean = sum(s * s for s in samples) / len(samples)
    return min(1.0, math.sqrt(mean) / 8000)


StreamFactory = Callable[..., Any]  # (callback) or (callback, device) -> a started stream
DeviceLister = Callable[[], list[Any]]


def _sounddevice():
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise VicoError(ErrorCode.MIC_UNAVAILABLE, "Audio support is not installed on this computer.") from exc
    return sd


def input_devices() -> list[Any]:
    """Every usable microphone, best first: the system default, then WASAPI, MME and the rest
    on Windows, or ALSA devices on Linux. 'Devices' that record the speakers are skipped and
    each physical mic appears once."""
    try:
        sd = _sounddevice()
        devices = list(sd.query_devices())
        apis = [a["name"] for a in sd.query_hostapis()]
        default = sd.default.device[0]
    except Exception:
        return [None]
    rank = {"Windows WASAPI": 0, "ALSA": 0, "MME": 1, "Windows DirectSound": 2}
    found: list[tuple[int, int]] = []
    for idx, dev in enumerate(devices):
        api = apis[dev["hostapi"]] if dev["hostapi"] < len(apis) else ""
        name = str(dev["name"]).lower()
        if dev["max_input_channels"] < 1 or api == "Windows WDM-KS" or any(k in name for k in _SKIP_INPUTS):
            continue
        found.append((rank.get(api, 3), idx))
    ordered: list[Any] = [None]  # None = the system default, always tried first
    seen: set[str] = set()
    if isinstance(default, int) and 0 <= default < len(devices):
        seen.add(str(devices[default]["name"])[:31].lower())
    for _, idx in sorted(found):
        key = str(devices[idx]["name"])[:31].lower()  # MME cuts names at 31 characters
        if key not in seen:
            seen.add(key)
            ordered.append(idx)
    return ordered


def device_name(device: Any) -> str:
    if device is None:
        return "default microphone"
    try:
        return str(_sounddevice().query_devices(device)["name"])
    except Exception:
        return f"microphone {device}"


def _default_stream(callback: Callable[[bytes], None], device: Any = None) -> Any:
    sd = _sounddevice()

    def on_audio(indata, frames, time_info, status):  # noqa: ARG001 - sounddevice signature
        callback(bytes(indata))

    extra = None
    try:
        info = sd.query_devices(device if device is not None else sd.default.device[0])
        if sd.query_hostapis(info["hostapi"])["name"] == "Windows WASAPI":
            extra = sd.WasapiSettings(auto_convert=True)  # WASAPI only opens at the mixer's rate otherwise
    except Exception:  # noqa: S110 - open without host-specific settings
        pass
    try:
        stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16", device=device,
                                   callback=on_audio, extra_settings=extra)
        stream.start()
        return stream
    except Exception as exc:
        raise VicoError(ErrorCode.MIC_UNAVAILABLE,
                        "No microphone could be opened. Check it is plugged in and that Vico may use it.",
                        status=409) from exc


class Recorder:
    def __init__(self, stream_factory: StreamFactory | None = None, max_seconds: float = MAX_RECORDING_SECONDS,
                 devices: DeviceLister | None = None):
        self._factory = stream_factory or _default_stream
        # A custom factory without a lister has one implicit device (tests).
        self._list_devices = devices or (input_devices if stream_factory is None else (lambda: [None]))
        self.max_seconds = max_seconds
        self._lock = threading.Lock()
        self._stream: Any = None
        self._chunks: list[bytes] = []
        self._bytes = 0
        self._started = 0.0
        self._opened = 0.0  # when the current device was opened
        self._peak = 0
        self._candidates: list[Any] = []
        self._first: Any = None  # the device tried first; Vico returns to it if none sounds alive
        self._settled = False  # stop trying other devices for this recording
        self._device: Any = None
        self._working: Any = None  # the device that last produced real sound
        self._known_working = False
        self.silent = False  # every microphone tried gives only digital silence
        self.language: str | None = None
        self.level = 0.0
        self._listeners: list[Callable[[bool], None]] = []

    def add_listener(self, listener: Callable[[bool], None]) -> None:
        """Called with True when recording starts and False when it ends (the wake phrase
        listener steps aside meanwhile)."""
        self._listeners.append(listener)

    def _notify(self, busy: bool) -> None:
        for listener in self._listeners:
            listener(busy)

    @property
    def preferred_device(self) -> Any:
        """The microphone that last produced real sound, or None for the system default."""
        return self._working if self._known_working else None

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
            self._peak = max(self._peak, peak(data))

    def _open_next(self) -> bool:
        """Open the next candidate microphone; False when none is left to try."""
        error: VicoError | None = None
        while self._candidates:
            device = self._candidates.pop(0)
            try:
                stream = self._factory(self._on_audio) if device is None else self._factory(self._on_audio, device)
            except VicoError as exc:
                error = exc
                continue
            self._stream, self._device, self._opened = stream, device, time.monotonic()
            return True
        if error is not None:
            raise error
        return False

    def start(self, language: str | None) -> None:
        with self._lock:
            if self._stream is not None:
                raise VicoError(ErrorCode.CONFLICT, "Already recording.", status=409)
            self._chunks, self._bytes, self.level, self._peak = [], 0, 0.0, 0
            self.silent = False
            self.language = language
            candidates = self._list_devices() or [None]
            if self._known_working and self._working in candidates:
                candidates = [self._working] + [d for d in candidates if d != self._working]
            self._candidates = candidates
            self._first, self._settled = candidates[0], False
            self._started = time.monotonic()
            self._open_next()
        self._notify(True)

    def _check_dead_device(self) -> None:
        """Move to the next microphone when this one has delivered only digital silence.

        Some microphones send exact zeros until someone speaks (noise suppression), so this
        never gives up: when no other device sounds alive either, it goes back to the first
        one and keeps recording there, only flagging `silent` as a hint."""
        if self._peak > DEAD_PEAK:
            self.silent = False
            return
        if self._stream is None or self._settled or self._bytes == 0:
            return
        if time.monotonic() - self._opened < PROBE_SECONDS:
            return
        self._close()
        self._chunks, self._bytes, self.level = [], 0, 0.0
        try:
            opened = self._open_next()
        except VicoError:
            opened = False
        if not opened:
            self.silent, self._settled = True, True
            self._candidates = [self._first]
            try:
                self._open_next()
            except VicoError:
                pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._check_dead_device()
            if self._peak > DEAD_PEAK and self._stream is not None:
                self._working, self._known_working = self._device, True
            elapsed = time.monotonic() - self._started if self.active else 0.0
            return {"recording": self.active, "elapsed_s": round(elapsed, 1), "max_s": self.max_seconds,
                    "level": round(self.level, 3), "full": self._bytes >= self.max_bytes,
                    "silent": self.silent, "device": device_name(self._device)}

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
            dead = self._peak <= DEAD_PEAK
            every_device_silent = self.silent
            if not dead:
                self._working, self._known_working = self._device, True
            self._chunks, self._bytes, self.level, self._peak = [], 0, 0.0, 0
        self._notify(False)
        seconds = len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)
        if dead and (every_device_silent or seconds >= MIN_SECONDS):
            raise VicoError(ErrorCode.MIC_UNAVAILABLE,
                            "I couldn't hear any sound from your microphone. Check it isn't muted, and that "
                            "Windows lets apps use it (Settings → Privacy → Microphone).", status=409)
        if seconds < MIN_SECONDS:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "That was too short. Speak a little longer.")
        if dead:
            raise VicoError(ErrorCode.MIC_UNAVAILABLE,
                            "Your microphone is muted or turned off. Turn it on in your sound settings, "
                            "or type instead.", status=409)
        if rms_level(pcm) < 0.005:
            raise VicoError(ErrorCode.VALIDATION_ERROR, "I couldn't hear you. Speak a little closer, or type instead.")
        return to_wav(normalize(pcm)), seconds

    def cancel(self) -> None:
        with self._lock:
            was_active = self._stream is not None
            self._close()
            self._chunks, self._bytes, self.level, self._peak = [], 0, 0.0, 0
        if was_active:
            self._notify(False)

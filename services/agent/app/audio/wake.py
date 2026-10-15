"""Calling Vico by name, recognised on this computer.

Any phrase with "Vico" in it wakes Vico: "Hey Vico", "Vico wassup", "Vico how far", "Okay
Vico, open Notepad". Vosk (Apache-2.0) with its small English model listens only for the name
and a few look-alike words. Audio heard
while waiting never leaves the computer and is never stored: each block is fed to the
recognizer and dropped. When the phrase is heard, the push-to-talk recorder starts at once
so the request that follows ("Hey Vico, open Notepad") is captured, and the desktop app is
told to come up.

The model ships with the installer; if it is missing it is downloaded once from Alpha Cephei,
its publisher, and used only if its SHA-256 matches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.audio.recorder import SAMPLE_RATE, Recorder, _default_stream
from app.config import data_dir
from app.contracts import VicoError

log = logging.getLogger(__name__)

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SHA256 = "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"  # 41,205,931 bytes
WAKE_WORD = "vico"
# Look-alike words give the recognizer somewhere to put near misses; everything else is [unk].
# Tested with Windows' David and Zira voices (28 of 28 right): "Hey Vico", "Vico wassup",
# "Vico how far", "Vico open notepad" and "Okay Vico" wake it; "the vehicle", "play the video",
# "Hey Victor", "Hey Rico", "Victoria is here" and "vicious dog" do not.
GRAMMAR = [WAKE_WORD, "vehicle", "video", "victor", "vicky", "rico", "vicious", "victoria", "[unk]"]
CLAIM_SECONDS = 4.0  # a wake the desktop app never picks up is dropped after this long


def is_wake(text: str) -> bool:
    return WAKE_WORD in str(text).lower().split()


def model_dir() -> Path:
    """Where the model is: next to a packaged engine if bundled, else in Vico's data folder."""
    bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "models" / MODEL_NAME
    return bundled if bundled.is_dir() else data_dir() / "models" / MODEL_NAME


def download_model(target: Path, fetch: Callable[[str], bytes] | None = None) -> None:
    """Fetch the model zip into memory, check its SHA-256, and unpack it safely."""
    if fetch is None:
        import httpx

        def fetch(url: str) -> bytes:
            with httpx.Client(follow_redirects=True, timeout=120) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content

    data = fetch(MODEL_URL)
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError(f"wake model checksum mismatch ({digest})")
    import io

    root = target.parent
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            resolved = (root / member).resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError(f"unsafe path in wake model archive: {member}")
        archive.extractall(root)


def _vosk_recognizer(path: Path) -> Any:
    import vosk

    vosk.SetLogLevel(-1)
    return vosk.KaldiRecognizer(vosk.Model(str(path)), SAMPLE_RATE, json.dumps(GRAMMAR))


class WakeWord:
    """Listens for the wake phrase whenever the recorder is idle."""

    def __init__(self, recorder: Recorder, *, stream_factory: Callable[..., Any] | None = None,
                 recognizer_factory: Callable[[Path], Any] | None = None,
                 prepare: Callable[[Path], None] | None = None):
        self.recorder = recorder
        self._open_stream = stream_factory or _default_stream
        self._make_recognizer = recognizer_factory or _vosk_recognizer
        self._prepare = prepare or download_model
        self._lock = threading.RLock()
        self._audio: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self._stream: Any = None
        self._recognizer: Any = None
        self._worker: threading.Thread | None = None
        self.wanted = False
        self.state = "off"  # off | preparing | listening | paused | unavailable
        self.error: str | None = None
        self._woke_at = 0.0  # monotonic time of an unclaimed wake, 0 if none
        self._wake_id = 0
        recorder.add_listener(self._recorder_busy)

    # --- control ------------------------------------------------------------------------
    def enable(self) -> None:
        with self._lock:
            self.wanted = True
            if self._recognizer is None and self.state != "preparing":
                self.state = "preparing"
                threading.Thread(target=self._load, name="vico-wake-load", daemon=True).start()
            elif self._recognizer is not None:
                self._start_listening()

    def disable(self) -> None:
        with self._lock:
            self.wanted = False
            self._stop_listening()
            self.state = "off"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"enabled": self.wanted, "state": self.state, "error": self.error}

    def claim(self) -> bool:
        """True once per wake: the desktop app takes over the recording that already started."""
        with self._lock:
            woke, self._woke_at = self._woke_at, 0.0
            return woke > 0 and time.monotonic() - woke < CLAIM_SECONDS and self.recorder.active

    def close(self) -> None:
        self.disable()
        self._audio.put(None)

    # --- internals ----------------------------------------------------------------------
    def _load(self) -> None:
        path = model_dir()
        try:
            if not (path / "conf" / "model.conf").exists():
                self._prepare(path)
            recognizer = self._make_recognizer(path)
        except Exception as exc:  # no network, bad download, missing library
            log.warning("wake phrase unavailable: %s", exc)
            with self._lock:
                self.state, self.error = "unavailable", "The 'Hey Vico' listener could not be prepared."
            return
        with self._lock:
            self._recognizer = recognizer
            self.error = None
            if self.wanted:
                self._start_listening()
            else:
                self.state = "off"

    def _start_listening(self) -> None:
        if self._stream is not None or not self.wanted or self._recognizer is None:
            return
        if self.recorder.active:
            self.state = "paused"
            return
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, name="vico-wake", daemon=True)
            self._worker.start()
        try:
            device = self.recorder.preferred_device
            self._stream = (self._open_stream(self._on_audio) if device is None
                            else self._open_stream(self._on_audio, device))
            self.state = "listening"
        except VicoError as exc:
            self.state, self.error = "unavailable", exc.message

    def _stop_listening(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: S110 - a vanished device must not break pausing
                pass
        if self._recognizer is not None:
            self._recognizer.Reset()

    def _recorder_busy(self, busy: bool) -> None:
        with self._lock:
            if busy:
                self._stop_listening()
                if self.wanted and self.state == "listening":
                    self.state = "paused"
            elif self.wanted and self._recognizer is not None:
                self._start_listening()

    def _on_audio(self, data: bytes) -> None:
        try:
            self._audio.put_nowait(data)
        except queue.Full:
            pass  # the recognizer is behind; dropping a block only delays recognition

    def _run(self) -> None:
        while True:
            data = self._audio.get()
            if data is None:
                return
            with self._lock:
                recognizer = self._recognizer if self._stream is not None else None
            if recognizer is None:
                continue
            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "")
            else:
                text = json.loads(recognizer.PartialResult()).get("partial", "")
            if is_wake(text):
                self._wake()

    def _wake(self) -> None:
        with self._lock:
            if self._stream is None:
                return
            self._stop_listening()
        try:
            self.recorder.start(None)  # pauses this listener through the busy callback
        except VicoError as exc:
            log.warning("wake heard but recording could not start: %s", exc.message)
            with self._lock:
                self._start_listening()
            return
        with self._lock:
            self._woke_at = time.monotonic()
            self._wake_id += 1
            timer = threading.Timer(CLAIM_SECONDS, self._drop_unclaimed, args=(self._wake_id,))
        timer.daemon = True
        timer.start()

    def _drop_unclaimed(self, wake_id: int) -> None:
        with self._lock:
            unclaimed = self._woke_at > 0 and wake_id == self._wake_id
            if unclaimed:
                self._woke_at = 0.0
        if unclaimed:
            self.recorder.cancel()  # nobody came for it: stop recording and listen again

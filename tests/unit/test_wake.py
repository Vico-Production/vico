import hashlib
import io
import json
import time
import zipfile

import pytest

import app.audio.wake as wake_module
from app.audio.recorder import Recorder
from app.audio.wake import WakeWord, download_model, is_wake


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.closed = False

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeRecognizer:
    """Hears whatever text was fed as bytes."""

    def __init__(self):
        self.text = ""

    def AcceptWaveform(self, data):  # noqa: N802 - Vosk's API
        self.text = data.decode()
        return True

    def Result(self):  # noqa: N802
        return json.dumps({"text": self.text})

    def PartialResult(self):  # noqa: N802
        return json.dumps({"partial": ""})

    def Reset(self):  # noqa: N802
        self.text = ""


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_module, "model_dir", lambda: tmp_path / "model")
    mic_streams: list[FakeStream] = []
    wake_streams: list[FakeStream] = []

    def mic(cb, device=None):
        s = FakeStream(cb)
        mic_streams.append(s)
        return s

    def wake_mic(cb, device=None):
        s = FakeStream(cb)
        wake_streams.append(s)
        return s

    recorder = Recorder(mic)
    wake = WakeWord(recorder, stream_factory=wake_mic, recognizer_factory=lambda path: FakeRecognizer(),
                    prepare=lambda path: None)
    yield wake, recorder, wake_streams, mic_streams
    wake.close()


def test_wake_phrases():
    assert is_wake("[unk] vico") and is_wake("vico [unk]") and is_wake("vico") and is_wake("Okay  Vico")
    assert not is_wake("[unk] victor") and not is_wake("vehicle") and not is_wake("[unk] video [unk]")
    assert not is_wake("vicovico") and not is_wake("")


def test_hearing_the_phrase_starts_recording_once(rig):
    wake, recorder, wake_streams, mic_streams = rig
    wake.enable()
    assert wait_for(lambda: wake.status()["state"] == "listening")
    wake_streams[0].callback(b"[unk] victor")
    time.sleep(0.1)
    assert not recorder.active and not wake.claim()
    wake_streams[0].callback(b"vico [unk]")
    assert wait_for(lambda: recorder.active)
    assert wake_streams[0].closed and wake.status()["state"] == "paused"
    assert wake.claim() is True and wake.claim() is False  # handed over exactly once
    recorder.cancel()
    assert wait_for(lambda: wake.status()["state"] == "listening")
    assert len(wake_streams) == 2  # listening again on a fresh stream


def test_manual_recording_pauses_listening(rig):
    wake, recorder, wake_streams, _ = rig
    wake.enable()
    assert wait_for(lambda: wake.status()["state"] == "listening")
    recorder.start(None)
    assert wake_streams[0].closed and wake.status()["state"] == "paused"
    recorder.cancel()
    assert wake.status()["state"] == "listening"


def test_unclaimed_wake_is_dropped(rig, monkeypatch):
    monkeypatch.setattr(wake_module, "CLAIM_SECONDS", 0.05)
    wake, recorder, wake_streams, _ = rig
    wake.enable()
    assert wait_for(lambda: wake.status()["state"] == "listening")
    wake_streams[0].callback(b"vico [unk]")
    assert wait_for(lambda: recorder.active)
    assert wait_for(lambda: not recorder.active)  # nobody claimed it, so it stops and listens again
    assert wait_for(lambda: wake.status()["state"] == "listening")


def test_disable_stops_listening(rig):
    wake, _, wake_streams, _ = rig
    wake.enable()
    assert wait_for(lambda: wake.status()["state"] == "listening")
    wake.disable()
    assert wake_streams[0].closed and wake.status() == {"enabled": False, "state": "off", "error": None}


def test_failed_preparation_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(wake_module, "model_dir", lambda: tmp_path / "model")

    def broken(path):
        raise OSError("offline")

    wake = WakeWord(Recorder(lambda cb: FakeStream(cb)), recognizer_factory=lambda p: FakeRecognizer(),
                    prepare=broken)
    wake.enable()
    assert wait_for(lambda: wake.status()["state"] == "unavailable")


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_model_download_checks_the_checksum(tmp_path, monkeypatch):
    archive = _zip({"vosk-model-small-en-us-0.15/conf/model.conf": b"x"})
    with pytest.raises(ValueError, match="checksum"):
        download_model(tmp_path / "vosk-model-small-en-us-0.15", fetch=lambda url: archive)
    monkeypatch.setattr(wake_module, "MODEL_SHA256", hashlib.sha256(archive).hexdigest())
    download_model(tmp_path / "vosk-model-small-en-us-0.15", fetch=lambda url: archive)
    assert (tmp_path / "vosk-model-small-en-us-0.15" / "conf" / "model.conf").read_bytes() == b"x"


def test_model_download_refuses_unsafe_paths(tmp_path, monkeypatch):
    archive = _zip({"../evil.txt": b"x"})
    monkeypatch.setattr(wake_module, "MODEL_SHA256", hashlib.sha256(archive).hexdigest())
    with pytest.raises(ValueError, match="unsafe"):
        download_model(tmp_path / "models" / "m", fetch=lambda url: archive)
    assert not (tmp_path / "models" / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()


class _Rec:
    """A recognizer that returns scripted results, one per block."""

    def __init__(self, script):
        self.script = list(script)
        self.now = None

    def AcceptWaveform(self, data):  # noqa: N802 - Vosk's name
        self.now = self.script.pop(0)
        return self.now[0] == "final"

    def Result(self):  # noqa: N802
        return json.dumps(self.now[1])

    def PartialResult(self):  # noqa: N802
        return json.dumps({"partial": self.now[1]})


def test_a_near_miss_seen_once_does_not_wake_but_a_real_call_does():
    from app.audio.wake import WakeDetector

    d = WakeDetector()
    rec = _Rec([("partial", "vico"), ("partial", "big")])  # a flicker, then gone
    assert [d.hears(rec, b"\0\0" * 1600) for _ in range(2)] == ["", ""]
    rec = _Rec([("partial", "vico"), ("partial", "vico")])
    assert [d.hears(rec, b"\0\0" * 1600) for _ in range(2)] == ["", "wake"]


def test_an_unsure_final_vico_does_not_wake():
    from app.audio.wake import WakeDetector

    d = WakeDetector()
    unsure = {"text": "vico", "result": [{"word": "vico", "conf": 0.3}]}
    sure = {"text": "vico", "result": [{"word": "vico", "conf": 0.9}]}
    assert d.hears(_Rec([("final", unsure)]), b"\0\0" * 1600) == ""
    assert d.hears(_Rec([("final", sure)]), b"\0\0" * 1600) == "wake"

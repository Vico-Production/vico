import array
import math
import wave
from io import BytesIO

import pytest

from app.audio.recorder import SAMPLE_RATE, Recorder
from app.contracts import VicoError
from app.store.db import Database
from app.store.history import HistoryRepository
from app.store.settings import SettingsPatch, SettingsRepository


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.closed = False

    def feed(self, seconds: float, amplitude: int = 6000):
        n = int(seconds * SAMPLE_RATE)
        samples = array.array("h", (int(amplitude * math.sin(i / 10)) for i in range(n)))
        self.callback(samples.tobytes())

    def stop(self):
        pass

    def close(self):
        self.closed = True


def make_recorder(max_seconds=15):
    streams = []

    def factory(cb):
        s = FakeStream(cb)
        streams.append(s)
        return s

    return Recorder(factory, max_seconds=max_seconds), streams


def test_record_produces_wav_and_closes_stream():
    rec, streams = make_recorder()
    rec.start("yo")
    streams[0].feed(1.0)
    wav, seconds = rec.stop()
    assert streams[0].closed and not rec.active
    assert abs(seconds - 1.0) < 0.01
    with wave.open(BytesIO(wav)) as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1


def test_recording_is_capped():
    rec, streams = make_recorder(max_seconds=2)
    rec.start("en")
    streams[0].feed(5.0)
    assert rec.status()["full"]
    _, seconds = rec.stop()
    assert seconds == pytest.approx(2.0)


def test_silence_and_short_clips_are_rejected():
    rec, streams = make_recorder()
    rec.start("en")
    streams[0].feed(1.0, amplitude=0)
    with pytest.raises(VicoError):
        rec.stop()
    rec.start("en")
    streams[1].feed(0.1)
    with pytest.raises(VicoError):
        rec.stop()


def test_cancel_and_double_start():
    rec, streams = make_recorder()
    rec.start("en")
    with pytest.raises(VicoError):
        rec.start("en")
    rec.cancel()
    assert streams[0].closed and not rec.active
    with pytest.raises(VicoError):
        rec.stop()


def test_missing_microphone_error():
    def factory(cb):
        raise VicoError("mic_unavailable", "no mic")

    rec = Recorder(factory)
    with pytest.raises(VicoError) as exc:
        rec.start("en")
    assert exc.value.code == "mic_unavailable" and not rec.active


def test_settings_round_trip(isolated_data_dir):
    db = Database(isolated_data_dir / "t.db")
    repo = SettingsRepository(db)
    assert repo.load().require_approval is True
    repo.update(SettingsPatch(require_approval=False, language="yo"))
    reopened = SettingsRepository(Database(isolated_data_dir / "t.db"))
    s = reopened.load()
    assert s.require_approval is False and s.language == "yo"


def test_history_add_list_clear(isolated_data_dir):
    repo = HistoryRepository(Database(isolated_data_dir / "h.db"))
    repo.add(language="en", summary="Create folder Demo with key gsk_abcdefghijklmnopqrstuvwxyz", tool="create_folder",
             approval="approved", outcome="succeeded", verified=True)
    items = repo.list()
    assert len(items) == 1 and "gsk_" not in items[0].summary
    assert repo.clear() == 1 and repo.list() == []


def test_corrupt_database_is_recovered(isolated_data_dir):
    path = isolated_data_dir / "bad.db"
    path.write_bytes(b"this is not sqlite" * 100)
    db = Database(path)
    assert SettingsRepository(db).load().require_approval is True
    assert path.with_suffix(".corrupt").exists()

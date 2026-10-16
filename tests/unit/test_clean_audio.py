import io
import time
import wave

import numpy as np

from app.audio.clean import _read, clean, snr_db

RATE = 16000


def wav(samples):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return out.getvalue()


def speechlike(seconds, amp=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    envelope = 0.5 * (1 + np.sign(np.sin(2 * np.pi * 3 * t)))  # syllable-like bursts
    return amp * envelope * (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 660 * t))


def test_noise_is_reduced_and_speech_kept():
    rng = np.random.default_rng(1)
    speech = np.concatenate([np.zeros(RATE), speechlike(2.0), np.zeros(RATE)])
    noisy = speech + 0.05 * rng.standard_normal(len(speech))  # a loud fan
    before = snr_db(noisy)
    started = time.perf_counter()
    out, _ = _read(clean(wav(noisy)))
    assert time.perf_counter() - started < 0.5  # fast enough to run on every request
    assert snr_db(out) > before + 6
    assert len(out) < len(noisy)  # the silent second at each end was trimmed (with a margin)


def test_quiet_speaker_is_raised_and_quiet_room_left_alone():
    quiet = np.concatenate([np.zeros(RATE // 2), speechlike(1.5, amp=0.01), np.zeros(RATE // 2)])
    out, _ = _read(clean(wav(quiet)))
    assert np.max(np.abs(out)) > 5 * np.max(np.abs(quiet))


def test_bad_audio_is_returned_unchanged():
    assert clean(b"not a wav") == b"not a wav"

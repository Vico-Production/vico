"""Cleaning a recording before it is transcribed, so every word comes through.

- A gentle high-pass removes rumble (fans, desk knocks, traffic) below 80 Hz.
- When the room is noisy, steady background noise (fans, generators, air conditioning,
  street hum) is reduced by spectral gating: the noise's spectrum is learned from the quietest
  part of the recording and subtracted, never below a floor, so speech is not distorted.
  In a quiet room nothing is changed: speech recognizers handle mild noise better on their
  own than after heavy filtering.
- Long silences before and after the speech are cut (with a margin), and the level is
  raised to a steady loudness, so quiet speakers are heard as well as loud ones.

Everything happens in memory on this computer.
"""

from __future__ import annotations

import io
import wave

import numpy as np

RATE = 16000
FRAME = 512  # 32 ms
HOP = 256
NOISY_SNR_DB = 18.0  # below this signal-to-noise ratio the background is reduced
REDUCTION = 0.85  # how much of the estimated noise is removed
FLOOR = 0.12  # never cut a frequency below this share of its level (keeps speech natural)
TARGET_RMS = 0.08  # about -22 dBFS for the speech part
MARGIN_S = 0.35


def _read(wav: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav)) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, rate


def _write(samples: np.ndarray, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes())
    return out.getvalue()


def _highpass(x: np.ndarray, rate: int, cutoff: float = 80.0) -> np.ndarray:
    # in the frequency domain, with a soft edge from 40 to 80 Hz
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / rate)
    spectrum *= np.clip((freqs - cutoff / 2) / (cutoff / 2), 0.0, 1.0)
    return np.fft.irfft(spectrum, n=len(x)).astype(np.float32)


def _frames_rms(x: np.ndarray) -> np.ndarray:
    n = max(1, (len(x) - FRAME) // HOP + 1)
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    idx = np.minimum(idx, len(x) - 1)
    return np.sqrt(np.mean(x[idx] ** 2, axis=1) + 1e-12)


def snr_db(x: np.ndarray) -> float:
    rms = _frames_rms(x)
    noise = np.percentile(rms, 10)
    speech = np.percentile(rms, 90)
    return float(20 * np.log10((speech + 1e-9) / (noise + 1e-9)))


def _reduce_noise(x: np.ndarray) -> np.ndarray:
    window = np.hanning(FRAME).astype(np.float32)
    n = max(1, (len(x) - FRAME) // HOP + 1)
    padded = np.concatenate([x, np.zeros(FRAME, dtype=np.float32)])
    frames = np.stack([padded[i * HOP:i * HOP + FRAME] * window for i in range(n)])
    spec = np.fft.rfft(frames, axis=1)
    mag, phase = np.abs(spec), np.angle(spec)
    energy = mag.mean(axis=1)
    quiet = mag[energy <= np.percentile(energy, 20)]  # the quietest fifth: background only
    noise = quiet.mean(axis=0) if len(quiet) else mag.min(axis=0)
    cleaned = np.maximum(mag - REDUCTION * noise[None, :], FLOOR * mag)
    out_frames = np.fft.irfft(cleaned * np.exp(1j * phase), n=FRAME, axis=1)
    out = np.zeros(n * HOP + FRAME, dtype=np.float32)
    norm = np.zeros_like(out)
    for i in range(n):
        out[i * HOP:i * HOP + FRAME] += out_frames[i] * window
        norm[i * HOP:i * HOP + FRAME] += window ** 2
    return (out / np.maximum(norm, 0.1 * float(norm.max())))[: len(x)]  # no boost at the very edges


def _trim(x: np.ndarray, rate: int) -> np.ndarray:
    rms = _frames_rms(x)
    level = max(np.percentile(rms, 15) * 3.0, 0.01)
    loud = np.nonzero(rms > level)[0]
    if len(loud) == 0:
        return x
    margin = int(MARGIN_S * rate)
    start = max(0, loud[0] * HOP - margin)
    end = min(len(x), loud[-1] * HOP + FRAME + margin)
    return x[start:end]


def clean(wav: bytes) -> bytes:
    """A clearer copy of a 16-bit PCM WAV recording; the original on any problem."""
    try:
        x, rate = _read(wav)
        if len(x) < rate // 4:
            return wav
        x = _highpass(x - float(np.mean(x)), rate)
        if snr_db(x) < NOISY_SNR_DB:
            x = _reduce_noise(x)
        x = _trim(x, rate)
        rms = _frames_rms(x)
        speech = float(np.percentile(rms, 90))
        if speech > 1e-4:
            x = x * min(8.0, TARGET_RMS / speech)  # raise quiet speech, never more than 18 dB
        return _write(x, rate)
    except Exception:  # never lose a recording to cleaning
        return wav

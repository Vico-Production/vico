import os
from pathlib import Path

import pytest

from app.providers import kokoro


def test_lexicon_reads_words_numbers_and_vico():
    lx = kokoro.Lexicon()
    p = lx.phonemes("Vico found 12 files.")
    assert p.startswith("vˈikO") and "twˈɛlv" in p and p.endswith(".")
    assert all(c in kokoro.VOCAB for c in p)


def test_number_words():
    assert kokoro.number_words(2026) == "two thousand twenty six"
    assert kokoro.number_words(115) == "one hundred and fifteen"


def test_checksum_mismatch_is_never_kept(tmp_path):
    folder = tmp_path / "kokoro"
    with pytest.raises(ValueError):
        kokoro.ensure_files(folder, fetch=lambda url: b"not the model")
    assert not any(folder.iterdir())


MODELS = Path(os.environ.get("APPDATA", str(Path.home() / ".local/share"))) / "Vico" / "models" / "kokoro"


@pytest.mark.skipif(not (MODELS / "kokoro-v1.0.int8.onnx").exists(), reason="model not downloaded here")
def test_kokoro_really_speaks():
    wav = kokoro.KokoroVoice(MODELS).speak("Done.")
    assert wav.startswith(b"RIFF") and len(wav) > 24_000

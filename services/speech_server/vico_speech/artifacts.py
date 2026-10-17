"""Model files the speech server may use, pinned to official repositories and checksums.

Every file comes from the publisher's own Hugging Face repository at a fixed commit and
is verified before use: LFS files by SHA-256 (as published in the repository's file
listing), small files by their git blob SHA-1. A file that does not match is deleted
and the server refuses to start. Checked against the repositories on 2026-10-15
(NaijaVox-2.0 on 2026-10-17).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    repo: str
    revision: str
    filename: str
    size: int
    sha256: str | None = None  # for LFS files
    git_sha1: str | None = None  # for small, non-LFS files
    license: str = ""


# Meta Omnilingual ASR, CTC 300M (Apache-2.0): the smallest speech-recognition model.
OMNI_CTC_300M = Artifact(
    repo="facebook/omniASR-CTC-300M",
    revision="8e35f0cc28fa6099e0c14d56db85ce0423baa691",
    filename="omniASR-CTC-300M.pt",
    size=1_302_113_892,
    sha256="4d31c6a7725a03e90cf26080c67361928755a9f43d322dd574145fbe91c76aec",
    license="Apache-2.0",
)
OMNI_TOKENIZER = Artifact(
    repo="facebook/omniASR-CTC-300M",
    revision="8e35f0cc28fa6099e0c14d56db85ce0423baa691",
    filename="omniASR_tokenizer.model",
    size=87_562,
    sha256="b954cc166b0c9e0271b953fa226fa27ca706a25b7029e84579fe2c60a2b451fe",
    license="Apache-2.0",
)

# YarnGPT2b (Apache-2.0): Nigerian voices for English, Yoruba, Igbo and Hausa.
YARN_MODEL = Artifact(
    repo="saheedniyi/YarnGPT2b",
    revision="eabc85c6d0ed44e4691d59dafc32d4255c215883",
    filename="model.safetensors",
    size=731_539_240,
    sha256="26dec40e13e31594ac304c64954051b0f55944b39d09857dc8e85fb94153fad8",
    license="Apache-2.0",
)
# WavTokenizer (MIT) audio decoder used by YarnGPT. The large checkpoint was removed from
# the official repo in a later commit, so it is pinned to the commit that still has it.
WAVTOKENIZER_CKPT = Artifact(
    repo="novateur/WavTokenizer-large-speech-75token",
    revision="1cc9faee31025548fbae6ffe11115d7207093638",
    filename="wavtokenizer_large_speech_320_24k.ckpt",
    size=1_754_880_958,
    sha256="7450020c154f6aba033cb8651466cb79cb1b1cdd10ea64eaba68e7871cabcc5a",
    license="MIT",
)
WAVTOKENIZER_CONFIG = Artifact(
    repo="novateur/WavTokenizer-medium-speech-75token",
    revision="8858552e69270816d6aeb37bfcf3b770769d4899",
    filename="wavtokenizer_mediumdata_frame75_3s_nq1_code4096_dim512_kmeans200_attn.yaml",
    size=2_791,
    git_sha1="50303443289262a371d3e5f6fc08602f5090bb6a",
    license="MIT",
)

# NaijaVox-2.0 (Apache-2.0): Whisper large-v3 fine-tuned for Yoruba, Hausa, Igbo, Nigerian
# Pidgin and Nigerian English (published WER: Pidgin 14.7%, English 19.6%, Yoruba 22.3%,
# Hausa 25.8%, Igbo 30.5%). Needs a GPU to be fast: about 1.5 billion parameters.
NAIJAVOX_REPO = "Axiveri/NaijaVox-2.0"
NAIJAVOX_REVISION = "22b94de94e59419cc9d6e25e6eaeceb1f1c42d00"
NAIJAVOX_MODEL = Artifact(
    repo=NAIJAVOX_REPO,
    revision=NAIJAVOX_REVISION,
    filename="model.safetensors",
    size=3_087_136_096,
    sha256="7d026e7088605bf2cfa35c8e00985ab4284f6a02ef29e80c2d2465556a6309f7",
    license="Apache-2.0",
)
NAIJAVOX_FILES = (  # small files, by git blob SHA-1
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "config.json", 1_225, git_sha1="7dae54dcf2b7441005ddc35756071e3899b05e9b"),
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "generation_config.json", 203,
             git_sha1="83c0143653f573939612e8c6e28d68f6e1eca026"),
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "preprocessor_config.json", 340,
             git_sha1="931c77a740890c46365c7ae0c9d350ba3cca908f"),
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "processor_config.json", 410,
             git_sha1="22755f693c72f1a96070a4fa82465ca007d5ab91"),
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "tokenizer.json", 3_931_010,
             git_sha1="30aa56235b1e59abfd56522389c9a0b8b219114c"),
    Artifact(NAIJAVOX_REPO, NAIJAVOX_REVISION, "tokenizer_config.json", 2_069,
             git_sha1="539cee294546d951e1f9ab6ba75cdfecb6040bb3"),
)

ASR_ARTIFACTS = (OMNI_CTC_300M, OMNI_TOKENIZER)
NAIJAVOX_ARTIFACTS = (NAIJAVOX_MODEL, *NAIJAVOX_FILES)
VOICE_ARTIFACTS = (YARN_MODEL, WAVTOKENIZER_CKPT, WAVTOKENIZER_CONFIG)

# YarnGPT's MIT-licensed helper code, pinned to a commit.
YARNGPT_CODE_REPO = "https://github.com/saheedniyi02/yarngpt.git"
YARNGPT_CODE_COMMIT = "8bb0eb27d307f4b5903149e24ecc1bd3caa4af2d"


class ChecksumError(RuntimeError):
    pass


def sha256_of(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


def verify(artifact: Artifact, path: Path) -> None:
    """Raise ChecksumError (and delete the file) unless it matches the pinned checksum."""
    if not path.is_file():
        raise ChecksumError(f"{artifact.filename} is missing")
    problem = None
    if path.stat().st_size != artifact.size:
        problem = f"size {path.stat().st_size} != {artifact.size}"
    elif artifact.sha256 and sha256_of(path) != artifact.sha256:
        problem = "SHA-256 does not match"
    elif artifact.git_sha1 and git_blob_sha1(path) != artifact.git_sha1:
        problem = "git SHA-1 does not match"
    if problem:
        path.unlink(missing_ok=True)
        raise ChecksumError(f"{artifact.repo}/{artifact.filename}: {problem}; the file was deleted")


def fetch(artifact: Artifact, models_dir: Path) -> Path:
    """Download from the official repo at the pinned commit (if needed) and verify."""
    target = models_dir / artifact.filename
    if target.is_file():
        verify(artifact, target)
        return target
    from huggingface_hub import hf_hub_download  # only needed on the server

    downloaded = Path(hf_hub_download(repo_id=artifact.repo, filename=artifact.filename,
                                      revision=artifact.revision, local_dir=models_dir))
    if downloaded != target:
        downloaded.replace(target)
    verify(artifact, target)
    return target

"""Vico's speech server on Modal (https://modal.com): a GPU only while you are talking.

Modal's free Starter plan includes $30 of compute a month with no card (checked 2026-10-17).
A T4 GPU costs about $0.59 an hour there, so the credit covers roughly 50 hours of the server
being awake; it sleeps (and costs nothing) after 5 quiet minutes. The first request after a
sleep takes about 30-60 s while the model loads; later ones about a second.

Deploy (once, from services/speech_server):
    pip install modal && modal setup
    modal secret create vico-speech VICO_SPEECH_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
    modal deploy deploy/modal_app.py
Then in Vico: Settings > Your speech server: paste the https://...modal.run address it prints
and the same token.
"""

import modal

app = modal.App("vico-speech")
models = modal.Volume.from_name("vico-speech-models", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi>=0.115", "numpy>=1.26", "huggingface_hub>=0.26", "torch", "transformers>=4.45")
    .add_local_python_source("vico_speech")
)


@app.function(
    image=image,
    gpu="T4",
    volumes={"/models": models},
    secrets=[modal.Secret.from_name("vico-speech")],
    scaledown_window=300,  # sleep after 5 quiet minutes
    timeout=600,
)
@modal.asgi_app()
def web():
    import os
    from pathlib import Path

    from vico_speech.engines import NaijaVoxRecognizer
    from vico_speech.server import create_app

    recognizer = NaijaVoxRecognizer(Path("/models"))  # downloads once into the volume, checksum-verified
    models.commit()
    return create_app(os.environ["VICO_SPEECH_TOKEN"], recognizer, None)

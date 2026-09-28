import os
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

_model: Optional[WhisperModel] = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        model_size = os.environ.get("WHISPER_MODEL_SIZE", "base")
        download_root = os.environ.get("WHISPER_MODEL_CACHE_DIR", "/data/whisper_models")
        _model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=download_root)
    return _model


def transcribe(video_path: Path) -> str:
    model = get_model()
    segments, _info = model.transcribe(str(video_path))
    return " ".join(segment.text.strip() for segment in segments).strip()

from pathlib import Path
from types import SimpleNamespace

from app.ingest import transcribe


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, path):
        return iter(self._segments), SimpleNamespace(language="it")


def test_transcribe_joins_segment_texts(monkeypatch):
    monkeypatch.setattr(
        transcribe, "get_model", lambda: FakeModel([FakeSegment(" Ciao "), FakeSegment("da Kyoto ")])
    )

    result = transcribe.transcribe(Path("/tmp/fake.mp4"))

    assert result == "Ciao da Kyoto"


def test_transcribe_returns_empty_string_for_no_segments(monkeypatch):
    monkeypatch.setattr(transcribe, "get_model", lambda: FakeModel([]))

    result = transcribe.transcribe(Path("/tmp/fake.mp4"))

    assert result == ""


def test_get_model_reads_env_vars_and_caches_instance(monkeypatch):
    captured = {}

    class RecordingWhisperModel:
        def __init__(self, model_size, device, compute_type, download_root):
            captured["model_size"] = model_size
            captured["device"] = device
            captured["compute_type"] = compute_type
            captured["download_root"] = download_root

    monkeypatch.setattr(transcribe, "WhisperModel", RecordingWhisperModel)
    monkeypatch.setattr(transcribe, "_model", None)
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")
    monkeypatch.setenv("WHISPER_MODEL_CACHE_DIR", "/tmp/whisper-cache")

    first = transcribe.get_model()
    second = transcribe.get_model()

    assert captured == {
        "model_size": "small",
        "device": "cpu",
        "compute_type": "int8",
        "download_root": "/tmp/whisper-cache",
    }
    assert first is second

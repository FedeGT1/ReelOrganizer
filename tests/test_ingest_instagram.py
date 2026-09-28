from pathlib import Path

import pytest

from app.ingest import instagram


class FakeYoutubeDL:
    should_fail = False
    description = "Una gita a Kyoto"
    write_file = True

    def __init__(self, opts):
        self.opts = opts
        self.download_dir = Path(opts["outtmpl"]).parent

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if type(self).should_fail:
            raise instagram.DownloadError("simulated failure")
        if type(self).write_file:
            (self.download_dir / "reel.mp4").write_bytes(b"fake video bytes")
        return {"description": type(self).description}


class FailingYoutubeDL(FakeYoutubeDL):
    should_fail = True


class NoFileYoutubeDL(FakeYoutubeDL):
    write_file = False


class NoCaptionYoutubeDL(FakeYoutubeDL):
    description = None


def test_fetch_returns_caption_and_video_path(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", FakeYoutubeDL)

    result = instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert result.caption == "Una gita a Kyoto"
    assert result.video_path == tmp_path / "reel.mp4"
    assert result.video_path.exists()


def test_fetch_raises_instagram_fetch_error_on_download_error(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", FailingYoutubeDL)

    with pytest.raises(instagram.InstagramFetchError):
        instagram.fetch("https://instagram.com/reel/private", tmp_path)


def test_fetch_raises_when_no_output_file_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", NoFileYoutubeDL)

    with pytest.raises(instagram.InstagramFetchError):
        instagram.fetch("https://instagram.com/reel/abc", tmp_path)


def test_fetch_defaults_caption_to_empty_string_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", NoCaptionYoutubeDL)

    result = instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert result.caption == ""

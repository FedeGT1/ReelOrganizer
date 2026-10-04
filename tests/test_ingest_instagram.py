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


class CapturingYoutubeDL(FakeYoutubeDL):
    captured_opts: dict | None = None

    def __init__(self, opts):
        super().__init__(opts)
        type(self).captured_opts = opts


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


def test_fetch_passes_cookiefile_when_cookies_file_exists_and_nonempty(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_file))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert CapturingYoutubeDL.captured_opts["cookiefile"] == str(cookies_file)


def test_fetch_omits_cookiefile_when_cookies_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(tmp_path / "does-not-exist.txt"))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert "cookiefile" not in CapturingYoutubeDL.captured_opts


def test_fetch_omits_cookiefile_when_cookies_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_file))

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert "cookiefile" not in CapturingYoutubeDL.captured_opts


def test_fetch_requests_a_format_that_includes_audio(tmp_path, monkeypatch):
    # Regression guard: Instagram exposes DASH adaptive formats (video-only
    # and audio-only) alongside legacy progressive muxed ones. A plain
    # "mp4/best" selector can resolve to the highest-resolution video-only
    # DASH stream, producing a video file with no audio track at all --
    # faster-whisper's decode_audio then raises IndexError (no audio stream
    # to read) instead of any caption-only-safe failure. This selector
    # guarantees an audio track is present: prefer an already-muxed format
    # that has one, otherwise merge the best video-only + audio-only pair.
    monkeypatch.setattr(instagram, "YoutubeDL", CapturingYoutubeDL)

    instagram.fetch("https://instagram.com/reel/abc", tmp_path)

    assert CapturingYoutubeDL.captured_opts["format"] == "best[acodec!=none]/bestvideo+bestaudio/best"

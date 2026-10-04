import os
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

YoutubeDL = yt_dlp.YoutubeDL
DownloadError = yt_dlp.utils.DownloadError

DEFAULT_COOKIES_PATH = "/data/instagram_cookies.txt"


class InstagramFetchError(Exception):
    pass


@dataclass
class FetchResult:
    caption: str
    video_path: Path


def cookies_path() -> Path:
    return Path(os.environ.get("INSTAGRAM_COOKIES_PATH", DEFAULT_COOKIES_PATH))


def fetch(url: str, download_dir: Path) -> FetchResult:
    ydl_opts = {
        "outtmpl": str(download_dir / "reel.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "format": "mp4/best",
    }
    cookies_file = cookies_path()
    if cookies_file.exists() and cookies_file.stat().st_size > 0:
        ydl_opts["cookiefile"] = str(cookies_file)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise InstagramFetchError(str(exc)) from exc

    matches = list(download_dir.glob("reel.*"))
    if not matches:
        raise InstagramFetchError("download completed but no output file was found")

    caption = (info or {}).get("description") or ""
    return FetchResult(caption=caption, video_path=matches[0])

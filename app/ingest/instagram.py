from dataclasses import dataclass
from pathlib import Path

import yt_dlp

YoutubeDL = yt_dlp.YoutubeDL
DownloadError = yt_dlp.utils.DownloadError


class InstagramFetchError(Exception):
    pass


@dataclass
class FetchResult:
    caption: str
    video_path: Path


def fetch(url: str, download_dir: Path) -> FetchResult:
    ydl_opts = {
        "outtmpl": str(download_dir / "reel.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "format": "mp4/best",
    }
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

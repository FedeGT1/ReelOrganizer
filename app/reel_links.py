import re
from typing import Optional
from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models import Reel

_SHORTCODE_RE = re.compile(r"^/(?:reel|reels|p)/([^/]+)")


def extract_reel_shortcode(link: str) -> Optional[str]:
    try:
        path = urlparse(link).path
    except ValueError:
        return None
    match = _SHORTCODE_RE.match(path)
    return match.group(1) if match else None


def reel_link_key(link: str) -> str:
    return extract_reel_shortcode(link) or link


def find_duplicate_reel(session: Session, link: str, user_id: str) -> Optional[Reel]:
    key = reel_link_key(link)
    for reel in session.exec(select(Reel).where(Reel.user_id == user_id)).all():
        if reel_link_key(reel.link) == key:
            return reel
    return None

import re
import unicodedata
from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_METERS = 6_371_000.0


def normalize_place_name(name: str) -> str:
    without_accents = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    without_parens = re.sub(r"\([^)]*\)", " ", without_accents)
    collapsed = re.sub(r"[^a-z0-9]+", " ", without_parens.lower())
    return collapsed.strip()


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * atan2(sqrt(a), sqrt(1 - a))

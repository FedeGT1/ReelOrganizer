"""Lat/lon -> SVG projection for the Japan map, and the pre-projected coastline.

Equirectangular projection with a cos(latitude) correction on longitude, so
the map isn't stretched east-west. The horizontal scale is fit to
VIEW_WIDTH; VIEW_HEIGHT is derived from that scale (not hand-picked) so
there's no wasted empty margin, plus a reserved strip at the bottom for the
Okinawa inset box - Okinawa sits far enough south that drawing it to true
scale would make the map absurdly tall (see design spec doc, section 3).
"""
import math

from app.coastline_data import JAPAN_COASTLINE_RINGS

VIEW_WIDTH = 440.0
PADDING = 25.0
INSET_HEIGHT = 130.0

_all_points = [pt for ring in JAPAN_COASTLINE_RINGS for pt in ring]
_lat0 = sum(lat for lat, _ in _all_points) / len(_all_points)
_cos_lat0 = math.cos(math.radians(_lat0))


def _equirect(lat: float, lon: float) -> tuple[float, float]:
    return lon * _cos_lat0, lat


_ex_all = [_equirect(lat, lon)[0] for lat, lon in _all_points]
_ey_all = [_equirect(lat, lon)[1] for lat, lon in _all_points]
_EX_MIN, _EX_MAX = min(_ex_all), max(_ex_all)
_EY_MIN, _EY_MAX = min(_ey_all), max(_ey_all)

_SCALE = (VIEW_WIDTH - 2 * PADDING) / (_EX_MAX - _EX_MIN)
_DRAWN_HEIGHT = (_EY_MAX - _EY_MIN) * _SCALE

VIEW_HEIGHT = _DRAWN_HEIGHT + 2 * PADDING + INSET_HEIGHT

INSET_BOX = {
    "x": PADDING,
    "y": PADDING + _DRAWN_HEIGHT + 15.0,
    "width": 110.0,
    "height": INSET_HEIGHT - 30.0,
}
INSET_MARKER = (
    INSET_BOX["x"] + INSET_BOX["width"] / 2,
    INSET_BOX["y"] + INSET_BOX["height"] * 0.65,
)
INSET_LABEL_POS = (INSET_BOX["x"] + INSET_BOX["width"] / 2, INSET_BOX["y"] + 18.0)


def project(lat: float, lon: float) -> tuple[float, float]:
    ex, ey = _equirect(lat, lon)
    x = PADDING + (ex - _EX_MIN) * _SCALE
    y = PADDING + (_EY_MAX - ey) * _SCALE
    return x, y


def _ring_to_path(ring: list[tuple[float, float]]) -> str:
    points = [project(lat, lon) for lat, lon in ring]
    start = f"M {points[0][0]:.2f},{points[0][1]:.2f}"
    rest = " ".join(f"L {x:.2f},{y:.2f}" for x, y in points[1:])
    return f"{start} {rest} Z"


COASTLINE_PATHS: list[str] = [_ring_to_path(ring) for ring in JAPAN_COASTLINE_RINGS]

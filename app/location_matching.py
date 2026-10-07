import re
import unicodedata
from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_METERS = 6_371_000.0


def normalize_place_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name or "")
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    without_parens = re.sub(r"\([^)]*\)", " ", without_marks)
    collapsed = re.sub(r"[^\w]+", " ", without_parens.lower())
    return collapsed.strip()


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * atan2(sqrt(a), sqrt(1 - a))


from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from sqlmodel import Session, select

from app.models import Location

NEW_HUB_SENTINEL = "__new_hub__"
AUTO_MATCH_DISTANCE_METERS = 150.0
NAME_SIMILARITY_THRESHOLD = 0.8
CANDIDATE_SEARCH_RADIUS_METERS = 2000.0
MAX_CANDIDATES = 5


@dataclass
class PlaceCandidate:
    id: str
    name: str
    distance_m: float


@dataclass
class HubOption:
    id: str
    name: str


@dataclass
class PlaceResolution:
    place_tier: str
    place_location_id: Optional[str]
    place_location_name: Optional[str]
    place_candidates: list[PlaceCandidate] = field(default_factory=list)
    hub_tier: str = "ambiguous"
    hub_id: Optional[str] = None
    hub_name: Optional[str] = None
    hub_options: list[HubOption] = field(default_factory=list)
    requires_confirmation: bool = False


def _resolve_hub(session: Session, near_hub: Optional[str]) -> tuple:
    normalized_near_hub = normalize_place_name(near_hub or "")
    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    if normalized_near_hub:
        for hub in hubs:
            if normalize_place_name(hub.name) == normalized_near_hub:
                return "auto", hub.id, hub.name
    return "ambiguous", None, None


def _hub_options(session: Session) -> list[HubOption]:
    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    return [HubOption(id=h.id, name=h.name) for h in hubs]


def _auto_place_resolution(session: Session, loc: Location, near_hub: Optional[str]) -> PlaceResolution:
    hub_tier, hub_id, hub_name = _resolve_hub(session, near_hub)
    return PlaceResolution(
        place_tier="auto",
        place_location_id=loc.id,
        place_location_name=loc.name,
        hub_tier=hub_tier,
        hub_id=hub_id,
        hub_name=hub_name,
        requires_confirmation=False,
    )


def resolve_place(
    session: Session,
    place_name: str,
    near_hub: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    exclude_location_id: Optional[str] = None,
) -> PlaceResolution:
    normalized_place = normalize_place_name(place_name)
    locations = session.exec(select(Location)).all()
    if exclude_location_id:
        locations = [loc for loc in locations if loc.id != exclude_location_id]

    if normalized_place:
        for loc in locations:
            normalized_loc = normalize_place_name(loc.name)
            if normalized_place == normalized_loc:
                return _auto_place_resolution(session, loc, near_hub)
            if loc.is_hub and normalized_place in normalized_loc:
                return _auto_place_resolution(session, loc, near_hub)

        if lat is not None and lon is not None:
            for loc in locations:
                if loc.lat is None or loc.lon is None:
                    continue
                distance = haversine_distance_m(float(lat), float(lon), loc.lat, loc.lon)
                ratio = SequenceMatcher(None, normalized_place, normalize_place_name(loc.name)).ratio()
                if distance <= AUTO_MATCH_DISTANCE_METERS and ratio >= NAME_SIMILARITY_THRESHOLD:
                    return _auto_place_resolution(session, loc, near_hub)

    candidates: list[PlaceCandidate] = []
    if lat is not None and lon is not None:
        scored = []
        for loc in locations:
            if loc.lat is None or loc.lon is None:
                continue
            distance = haversine_distance_m(float(lat), float(lon), loc.lat, loc.lon)
            if distance <= CANDIDATE_SEARCH_RADIUS_METERS:
                scored.append((distance, loc))
        scored.sort(key=lambda pair: pair[0])
        candidates = [
            PlaceCandidate(id=loc.id, name=loc.name, distance_m=round(distance, 1))
            for distance, loc in scored[:MAX_CANDIDATES]
        ]

    hub_tier, hub_id, hub_name = _resolve_hub(session, near_hub)

    return PlaceResolution(
        place_tier="ambiguous",
        place_location_id=None,
        place_location_name=None,
        place_candidates=candidates,
        hub_tier=hub_tier,
        hub_id=hub_id,
        hub_name=hub_name,
        hub_options=_hub_options(session),
        requires_confirmation=bool(candidates) or hub_tier == "ambiguous",
    )

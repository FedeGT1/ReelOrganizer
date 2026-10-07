from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.location_matching import AUTO_MATCH_DISTANCE_METERS, normalize_place_name, resolve_place
from app.models import Location
from app.routers.locations import _merge_locations, _reel_counts
from app.web import templates

ui_router = APIRouter(prefix="/ui/audit", tags=["audit-ui"])

REVIEW_NAME_SIMILARITY_THRESHOLD = 0.5


@dataclass
class AuditPair:
    a: Location
    b: Location
    a_count: int
    b_count: int
    distance_m: Optional[float] = None


def _effective_coords(loc: Location, by_id: dict) -> tuple:
    if loc.parent_id:
        parent = by_id.get(loc.parent_id)
        if parent is not None and loc.lat == parent.lat and loc.lon == parent.lon:
            # Coordinates inherited verbatim from the parent hub (the AI
            # import's missing-coordinates safety net) carry no real
            # proximity information -- comparing by distance would just
            # match this location against every other satellite that also
            # inherited the same hub's coordinates.
            return None, None
    return loc.lat, loc.lon


def _worth_reviewing(loc_name: str, other_name: str, distance_m: float) -> bool:
    if distance_m <= AUTO_MATCH_DISTANCE_METERS:
        # Suspiciously co-located (e.g. two different shops in the same
        # building) is worth a glance even with unrelated names.
        return True
    ratio = SequenceMatcher(None, normalize_place_name(loc_name), normalize_place_name(other_name)).ratio()
    return ratio >= REVIEW_NAME_SIMILARITY_THRESHOLD


def _find_anomalies(session: Session) -> dict:
    locations = session.exec(select(Location)).all()
    reel_counts = _reel_counts(session)
    by_id = {loc.id: loc for loc in locations}

    certain_keys: set = set()
    certain_pairs: list[AuditPair] = []
    for loc in locations:
        lat, lon = _effective_coords(loc, by_id)
        resolution = resolve_place(session, loc.name, None, lat, lon, exclude_location_id=loc.id)
        if resolution.place_tier == "auto":
            other = by_id[resolution.place_location_id]
            if other.is_hub != loc.is_hub:
                # A hub (city) and a satellite (a specific place in that
                # city) can never legitimately be the same place -- only
                # compare same-type locations for duplicates.
                continue
            key = frozenset((loc.id, other.id))
            if key not in certain_keys:
                certain_keys.add(key)
                certain_pairs.append(AuditPair(
                    a=loc, b=other,
                    a_count=reel_counts.get(loc.id, 0), b_count=reel_counts.get(other.id, 0),
                ))

    # Second pass, after every `auto` pair is known, so a pair already
    # classified as certain from one location's scan never also shows up
    # here just because the other location's scan only found it as a
    # candidate (resolve_place's tiers are directional).
    review_keys: set = set()
    review_pairs: list[AuditPair] = []
    for loc in locations:
        lat, lon = _effective_coords(loc, by_id)
        resolution = resolve_place(session, loc.name, None, lat, lon, exclude_location_id=loc.id)
        for candidate in resolution.place_candidates:
            other = by_id[candidate.id]
            if other.is_hub != loc.is_hub:
                continue
            if not _worth_reviewing(loc.name, other.name, candidate.distance_m):
                continue
            key = frozenset((loc.id, other.id))
            if key in certain_keys or key in review_keys:
                continue
            review_keys.add(key)
            review_pairs.append(AuditPair(
                a=loc, b=other,
                a_count=reel_counts.get(loc.id, 0), b_count=reel_counts.get(other.id, 0),
                distance_m=candidate.distance_m,
            ))

    return {"certain_pairs": certain_pairs, "review_pairs": review_pairs, "error": None}


@ui_router.get("/scan")
def ui_audit_scan(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))


@ui_router.post("/merge/{keep_id}/{drop_id}")
def ui_audit_merge(request: Request, keep_id: str, drop_id: str, session: Session = Depends(get_session)):
    try:
        _merge_locations(session, keep_id, drop_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        context = _find_anomalies(session)
        context["error"] = "Impossibile unire: la location da eliminare ha ancora città satellite collegate."
        return templates.TemplateResponse(request, "partials/audit_results.html", context)
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))

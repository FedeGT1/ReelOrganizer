from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.location_matching import normalize_place_name, resolve_place
from app.models import Location, Reel
from app.routers.categories import get_taxonomy
from app.routers.locations import _merge_locations
from app.routers.reels import _serialize_reel
from app.web import templates

ui_router = APIRouter(prefix="/ui/audit", tags=["audit-ui"])

REVIEW_NAME_SIMILARITY_THRESHOLD = 0.5


@dataclass
class AuditPair:
    a: Location
    b: Location
    a_reels: list = field(default_factory=list)
    b_reels: list = field(default_factory=list)
    distance_m: Optional[float] = None


@dataclass
class ImpreciseLocation:
    location: Location
    hub: Location
    reels: list = field(default_factory=list)


@dataclass
class LowConfidenceLocation:
    location: Location
    reels: list = field(default_factory=list)


@dataclass
class SplitCandidate:
    link: str
    location: Location
    reels: list = field(default_factory=list)


def _reels_for_location(session: Session, location_id: str) -> list:
    reels = session.exec(select(Reel).where(Reel.location_id == location_id)).all()
    return [_serialize_reel(session, r) for r in reels]


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


def _worth_reviewing(loc_name: str, other_name: str) -> bool:
    # Real-data evidence: dense areas (shopping districts, temple
    # complexes) routinely place several genuinely distinct, unrelated
    # places within even a few meters of each other -- proximity alone,
    # at any distance, is not a useful duplicate signal without some
    # name correlation too. Word-set overlap (not raw character overlap)
    # avoids being fooled by a shared district/chain word (e.g. both
    # names containing "Akihabara" or "Shinjuku").
    words_a = set(normalize_place_name(loc_name).split())
    words_b = set(normalize_place_name(other_name).split())
    if not words_a or not words_b:
        return False
    jaccard = len(words_a & words_b) / len(words_a | words_b)
    return jaccard >= REVIEW_NAME_SIMILARITY_THRESHOLD


def _find_imprecise_coordinates(session: Session, locations: list, by_id: dict) -> list:
    result = []
    for loc in locations:
        if loc.is_hub or not loc.parent_id:
            continue
        parent = by_id.get(loc.parent_id)
        if parent is not None and loc.lat == parent.lat and loc.lon == parent.lon:
            result.append(ImpreciseLocation(
                location=loc, hub=parent, reels=_reels_for_location(session, loc.id),
            ))
    return result


def _find_low_confidence(session: Session, locations: list) -> list:
    return [
        LowConfidenceLocation(location=loc, reels=_reels_for_location(session, loc.id))
        for loc in locations
        if loc.geocode_confidence == "low"
    ]


def _find_split_candidates(session: Session, by_id: dict) -> list:
    reels = session.exec(select(Reel)).all()
    groups: dict = {}
    for r in reels:
        groups.setdefault((r.link, r.location_id), []).append(r)

    result = []
    for (link, location_id), group in groups.items():
        if len(group) > 1:
            result.append(SplitCandidate(
                link=link,
                location=by_id[location_id],
                reels=[_serialize_reel(session, r) for r in group],
            ))
    return result


def _find_anomalies(session: Session) -> dict:
    locations = session.exec(select(Location)).all()
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
                    a_reels=_reels_for_location(session, loc.id),
                    b_reels=_reels_for_location(session, other.id),
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
            if not _worth_reviewing(loc.name, other.name):
                continue
            key = frozenset((loc.id, other.id))
            if key in certain_keys or key in review_keys:
                continue
            review_keys.add(key)
            review_pairs.append(AuditPair(
                a=loc, b=other,
                a_reels=_reels_for_location(session, loc.id),
                b_reels=_reels_for_location(session, other.id),
                distance_m=candidate.distance_m,
            ))

    return {
        "certain_pairs": certain_pairs,
        "review_pairs": review_pairs,
        "imprecise_locations": _find_imprecise_coordinates(session, locations, by_id),
        "low_confidence_locations": _find_low_confidence(session, locations),
        "split_candidates": _find_split_candidates(session, by_id),
        "taxonomy": get_taxonomy(session),
        "error": None,
    }


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

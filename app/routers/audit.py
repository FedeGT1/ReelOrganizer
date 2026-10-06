from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.location_matching import resolve_place
from app.models import Location
from app.routers.locations import _merge_locations, _reel_counts
from app.web import templates

ui_router = APIRouter(prefix="/ui/audit", tags=["audit-ui"])


@dataclass
class AuditPair:
    a: Location
    b: Location
    a_count: int
    b_count: int
    distance_m: Optional[float] = None


def _find_anomalies(session: Session) -> dict:
    locations = session.exec(select(Location)).all()
    reel_counts = _reel_counts(session)
    by_id = {loc.id: loc for loc in locations}

    certain_keys: set = set()
    certain_pairs: list[AuditPair] = []
    for loc in locations:
        resolution = resolve_place(session, loc.name, None, loc.lat, loc.lon, exclude_location_id=loc.id)
        if resolution.place_tier == "auto":
            key = frozenset((loc.id, resolution.place_location_id))
            if key not in certain_keys:
                certain_keys.add(key)
                other = by_id[resolution.place_location_id]
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
        resolution = resolve_place(session, loc.name, None, loc.lat, loc.lon, exclude_location_id=loc.id)
        for candidate in resolution.place_candidates:
            key = frozenset((loc.id, candidate.id))
            if key in certain_keys or key in review_keys:
                continue
            review_keys.add(key)
            other = by_id[candidate.id]
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

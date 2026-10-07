import json
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
from app.db import get_session
from app.location_matching import NEW_HUB_SENTINEL, normalize_place_name, resolve_place
from app.models import Location, Reel, ReelType
from app.routers.categories import get_taxonomy, get_valid_type_keys
from app.routers.locations import _merge_locations
from app.routers.reels import _serialize_reel
from app.web import templates

logger = logging.getLogger("app.ai")

ui_router = APIRouter(prefix="/ui/audit", tags=["audit-ui"])

REVIEW_NAME_SIMILARITY_THRESHOLD = 0.5


@dataclass
class AuditPair:
    a: Location
    b: Location
    a_reels: list = field(default_factory=list)
    b_reels: list = field(default_factory=list)
    distance_m: Optional[float] = None
    ai_verdict: Optional[dict] = None


@dataclass
class GeocodeProposal:
    lat: Optional[float]
    lon: Optional[float]
    confidence: Optional[str]
    error: Optional[str] = None


@dataclass
class ImpreciseLocation:
    location: Location
    reason: str
    reels: list = field(default_factory=list)
    proposal: Optional[GeocodeProposal] = None


@dataclass
class LowConfidenceLocation:
    location: Location
    reels: list = field(default_factory=list)
    proposal: Optional[GeocodeProposal] = None


@dataclass
class SplitCandidate:
    link: str
    location: Location
    reels: list = field(default_factory=list)
    proposals: Optional[list] = None


@dataclass
class SplitProposal:
    reel_id: str
    place_name: str
    note: str
    resolution: object
    place_json: str
    error: Optional[str] = None


def _reels_for_location(session: Session, location_id: str) -> list:
    reels = session.exec(select(Reel).where(Reel.location_id == location_id)).all()
    return [_serialize_reel(session, r) for r in reels]


def _effective_coords(loc: Location, by_id: dict) -> tuple:
    if loc.lat == 0 and loc.lon == 0:
        # "Null island" is never a real place -- it carries no proximity
        # information (same reasoning as hub-inherited coordinates below).
        return None, None
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
        if loc.lat == 0 and loc.lon == 0:
            # "Null island" -- never a real place in Japan, a classic
            # sentinel/default value from a bug or a bad manual edit.
            # Checked for every location, hub or satellite.
            result.append(ImpreciseLocation(
                location=loc,
                reason="coordinate a 0,0 -- quasi certamente un errore, nessun posto in Giappone è lì",
                reels=_reels_for_location(session, loc.id),
            ))
            continue

        if loc.is_hub or not loc.parent_id:
            continue
        parent = by_id.get(loc.parent_id)
        if parent is not None and loc.lat == parent.lat and loc.lon == parent.lon:
            result.append(ImpreciseLocation(
                location=loc,
                reason=f"coordinate ereditate da {parent.name}",
                reels=_reels_for_location(session, loc.id),
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


def _propose_split(session: Session, candidate: SplitCandidate) -> list:
    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}
    valid_type_keys = get_valid_type_keys(session)

    proposals = []
    for reel in candidate.reels:
        try:
            result = ai_client.categorize(
                hub_names, category_labels, [{"role": "user", "content": reel["note"] or ""}]
            )
        except (AIProviderError, RuntimeError):
            logger.exception("categorize call failed during split proposal for reel=%s", reel["id"])
            proposals.append(SplitProposal(
                reel_id=reel["id"], place_name="", note=reel["note"] or "",
                resolution=None, place_json="",
                error="Errore nel contattare l'assistente, riprova.",
            ))
            continue

        types = [t for t in result.get("types", []) if t in valid_type_keys]
        place_name = result.get("place_name", "")
        resolution = resolve_place(session, place_name, result.get("near_hub"), result.get("lat"), result.get("lon"))

        place_payload = {
            "reel_id": reel["id"],
            "place_name": place_name,
            "note": reel["note"] or "",
            "types": types,
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "confidence": result.get("confidence"),
            "resolution_location_id": resolution.place_location_id if resolution.place_tier == "auto" else "",
            "resolution_hub_id": resolution.hub_id if resolution.hub_tier == "auto" else "",
        }
        proposals.append(SplitProposal(
            reel_id=reel["id"], place_name=place_name, note=reel["note"] or "",
            resolution=resolution, place_json=json.dumps(place_payload),
        ))
    return proposals


def _reassign_reel_location(
    session: Session,
    reel_id: str,
    place_name: str,
    types: list,
    lat,
    lon,
    resolution_location_id: str,
    resolution_hub_id: str = "",
    confidence: Optional[str] = None,
) -> Reel:
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    if resolution_location_id:
        location_id = resolution_location_id
    else:
        if not lat or not lon:
            raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
        if not resolution_hub_id:
            raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

        is_hub = resolution_hub_id == NEW_HUB_SENTINEL
        new_location = Location(
            name=place_name,
            is_hub=is_hub,
            parent_id=None if is_hub else resolution_hub_id,
            lat=float(lat),
            lon=float(lon),
            geocode_confidence=confidence or None,
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel.location_id = location_id
    session.add(reel)

    valid_type_keys = get_valid_type_keys(session)
    for existing in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(existing)
    session.commit()
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel


def _propose_geocode(session: Session, location: Location) -> GeocodeProposal:
    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    notes = [r["note"] for r in _reels_for_location(session, location.id) if r["note"]]
    message = location.name if not notes else f"{location.name}. {' '.join(notes)}"

    try:
        result = ai_client.categorize(hub_names, category_labels, [{"role": "user", "content": message}])
    except (AIProviderError, RuntimeError):
        logger.exception("categorize call failed during geocode proposal for location=%s", location.id)
        return GeocodeProposal(
            lat=None, lon=None, confidence=None,
            error="Errore nel contattare l'assistente, riprova.",
        )

    return GeocodeProposal(lat=result.get("lat"), lon=result.get("lon"), confidence=result.get("confidence"))


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


@ui_router.post("/ai/compare/{location_a_id}/{location_b_id}")
def ui_audit_ai_compare(
    request: Request, location_a_id: str, location_b_id: str, session: Session = Depends(get_session)
):
    loc_a = session.get(Location, location_a_id)
    loc_b = session.get(Location, location_b_id)
    if loc_a is None or loc_b is None:
        raise HTTPException(status_code=404, detail="Location not found")

    notes_a = [r["note"] for r in _reels_for_location(session, loc_a.id) if r["note"]]
    notes_b = [r["note"] for r in _reels_for_location(session, loc_b.id) if r["note"]]

    try:
        verdict = ai_client.compare_places(loc_a.name, notes_a, loc_b.name, notes_b)
    except (AIProviderError, RuntimeError):
        logger.exception("compare_places call failed for %s vs %s", loc_a.id, loc_b.id)
        verdict = {"same_place": None, "reasoning": "Errore nel contattare l'assistente, riprova."}

    context = _find_anomalies(session)
    target_key = frozenset((loc_a.id, loc_b.id))
    for pair in context["certain_pairs"] + context["review_pairs"]:
        if frozenset((pair.a.id, pair.b.id)) == target_key:
            pair.ai_verdict = verdict
            break

    return templates.TemplateResponse(request, "partials/audit_results.html", context)


# Registered before /ai/split/{location_id} -- Starlette matches routes in
# registration order, and the dynamic path would otherwise swallow this
# literal one (treating "apply" as a location_id).
@ui_router.post("/ai/split/apply")
def ui_audit_ai_split_apply(
    request: Request, place_json: list[str] = Form([]), session: Session = Depends(get_session)
):
    parsed_places = []
    for raw in place_json:
        try:
            parsed_places.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry in split apply")

    for place in parsed_places:
        if not place.get("resolution_location_id"):
            if not place.get("lat") or not place.get("lon"):
                raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
            if not place.get("resolution_hub_id"):
                raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

    for place in parsed_places:
        _reassign_reel_location(
            session,
            place["reel_id"],
            place.get("place_name", ""),
            place.get("types", []),
            place.get("lat"),
            place.get("lon"),
            place.get("resolution_location_id", ""),
            place.get("resolution_hub_id", ""),
            place.get("confidence"),
        )

    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))


@ui_router.post("/ai/split/{location_id}")
def ui_audit_ai_split(
    request: Request, location_id: str, link: str = Form(...), session: Session = Depends(get_session)
):
    context = _find_anomalies(session)
    for candidate in context["split_candidates"]:
        if candidate.location.id == location_id and candidate.link == link:
            candidate.proposals = _propose_split(session, candidate)
            break
    return templates.TemplateResponse(request, "partials/audit_results.html", context)


@ui_router.post("/ai/geocode/apply/{location_id}")
def ui_audit_ai_geocode_apply(
    request: Request,
    location_id: str,
    lat: float = Form(...),
    lon: float = Form(...),
    confidence: str = Form(""),
    session: Session = Depends(get_session),
):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    location.lat = lat
    location.lon = lon
    location.geocode_confidence = confidence or None
    session.add(location)
    session.commit()
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))


@ui_router.post("/ai/geocode/{location_id}")
def ui_audit_ai_geocode(request: Request, location_id: str, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    proposal = _propose_geocode(session, location)

    context = _find_anomalies(session)
    for item in context["imprecise_locations"] + context["low_confidence_locations"]:
        if item.location.id == location_id:
            item.proposal = proposal

    return templates.TemplateResponse(request, "partials/audit_results.html", context)


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

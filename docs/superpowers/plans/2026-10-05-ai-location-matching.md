# AI Location Matching & Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the AI import flow's silent, error-prone location-matching heuristics (exact-match-only hub resolution that silently promotes mismatches to brand-new hubs; unqualified bidirectional substring matching for satellites) with a tiered algorithm that auto-matches only when genuinely confident, and otherwise asks the user to confirm instead of guessing.

**Architecture:** A new pure-logic module (`app/location_matching.py`) implements name normalization, distance calculation, and a `resolve_place()` function returning a `PlaceResolution` with independent place/hub tiers. Both the single-place (`ai_categorize.py`) and multi-place (`ai_multi_categorize.py`) flows call this one function and render a shared confirmation UI pattern: no extra control when confident, an explicit picker (pre-selected to "new place") when not.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, Jinja2, htmx, vanilla JS. No new dependencies — name similarity uses stdlib `difflib.SequenceMatcher`, distance uses a hand-rolled haversine (stdlib `math`).

**Spec:** `docs/superpowers/specs/2026-10-05-ai-location-matching-design.md`

## Global Constraints

- No database schema changes (spec: "Non-goals" — `Reel.location_id` already allows multiple reels per location; this is unchanged, existing behavior, not introduced here).
- No new third-party dependencies — `difflib` and `math` are stdlib.
- `AUTO_MATCH_DISTANCE_METERS = 150.0`, `NAME_SIMILARITY_THRESHOLD = 0.8`, `CANDIDATE_SEARCH_RADIUS_METERS = 2000.0`, `MAX_CANDIDATES = 5` (spec §Design 1 — exact values, tunable later but these are the starting constants).
- Auto-match for a place requires normalized-exact name match (any tier) OR (similarity ≥ 0.8 AND distance ≤ 150m) — never distance alone, specifically so two differently-named places sharing coordinates (same building, different shop) never silently merge (spec §Design 1, tier 2).
- A brand-new top-level hub is only ever created via the user's explicit `"__new_hub__"` choice — never as a silent fallback (spec §Design 1, point 4; §Design 3).
- Reusing an existing location never modifies that `Location` row's `name`/`lat`/`lon`/`geocode_confidence` — the new reel is simply a second `Reel` row pointing at it (spec §Non-goals, confirmed in conversation: this is pre-existing, unchanged behavior).
- `/api/ai/categorize`'s JSON response contract (`CategorizeResponse.matched_location_id`) stays exactly as-is (`Optional[str]`, `None` unless an auto-match tier fired) — this plan does not touch that public contract, only the two `/ui/ai/...` confirm flows gain new form fields.

## Review Focus

- **Empty/whitespace-only `place_name`.** Must never auto-match any location (tier 1's hub-containment check explicitly requires the normalized place name to be non-empty before testing substring containment, otherwise `"" in anything"` is vacuously true and would wrongly match the first hub). Covered in Task 2.
- **Creating a "new" location with no hub choice at all** (`resolution_location_id=""` and `resolution_hub_id=""`, e.g. a stale/crafted form submission after the picker rendered but before the user touched it). Must raise 400, not silently create an orphan satellite with `parent_id=None, is_hub=False`. Covered in Task 3.
- **Two differently-named locations at (near-)identical coordinates** (e.g. two shops in the same building) must never auto-merge — this is the scenario the user explicitly flagged. Covered in Task 2 (tier 2 requires both signals, not distance alone).
- **A real duplicate whose names differ only by punctuation/parenthetical content** (the "Surugaya - Akihabara" vs "Surugaya Akihabara (駿河屋秋葉原)" case from the live data) must resolve to the same location via normalization, not create a second row. Covered in Task 2.
- **More than `MAX_CANDIDATES` existing locations within the suggestion radius** must not flood the confirmation picker — capped and sorted nearest-first. Covered in Task 2.

---

## File Structure

**Create:**
- `app/location_matching.py` — pure logic: `normalize_place_name`, `haversine_distance_m`, `PlaceCandidate`, `HubOption`, `PlaceResolution`, `resolve_place`, `NEW_HUB_SENTINEL`.
- `tests/test_location_matching.py` — unit tests for the above.

**Modify:**
- `app/routers/ai_categorize.py` — remove `_find_matching_location`/`_find_hub_by_name`; `_apply_result_post_processing`, `_build_ai_chat_context`, `_resolve_location_and_create_reel`, `ui_ai_confirm` all switch to `resolve_place`/explicit resolution fields.
- `app/templates/partials/ai_chat.html` — confirm block renders confident info text or an explicit picker.
- `app/routers/ai_multi_categorize.py` — `_build_multi_context` computes a `resolution` per row; `ui_ai_multi_confirm` reads `resolution_location_id`/`resolution_hub_id` from each row's `place_json` instead of `matched_location_id`.
- `app/templates/partials/ai_chat_multi.html` — per-row confirm block, using a small JS helper to patch the row's embedded `place_json` when the user changes a picker.
- `app/static/js/ai-multi-resolution.js` (new file, included from `base.html`) — the JS helper above.
- `app/templates/base.html` — one new `<script>` include.
- `tests/test_ai_categorize.py`, `tests/test_ai_ui.py`, `tests/test_ai_multi_categorize.py` — updated for the new contract.

---

### Task 1: `location_matching.py` helpers — `normalize_place_name` and `haversine_distance_m`

**Files:**
- Create: `app/location_matching.py`
- Test: `tests/test_location_matching.py`

**Interfaces:**
- Produces: `normalize_place_name(name: str) -> str`, `haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float` — both pure, no DB access. Used by Task 2.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_location_matching.py
from app.location_matching import haversine_distance_m, normalize_place_name


def test_normalize_place_name_lowercases_and_strips():
    assert normalize_place_name("  Ichiran Ramen  ") == "ichiran ramen"


def test_normalize_place_name_strips_diacritics():
    assert normalize_place_name("Kōtoku-in") == "kotoku in"


def test_normalize_place_name_removes_parenthetical_content():
    assert normalize_place_name("Surugaya Akihabara (駿河屋秋葉原)") == "surugaya akihabara"


def test_normalize_place_name_collapses_punctuation_variants_to_the_same_string():
    assert normalize_place_name("Surugaya - Akihabara") == normalize_place_name(
        "Surugaya Akihabara (駿河屋秋葉原)"
    )


def test_normalize_place_name_empty_string_stays_empty():
    assert normalize_place_name("") == ""


def test_normalize_place_name_short_name_substring_check_against_hub_label():
    # Exercised directly here because it's the exact relationship Task 2's
    # tier-1 hub-containment check relies on.
    assert normalize_place_name("Tokyo") in normalize_place_name("Tokyo / Kanto")
    assert normalize_place_name("Hakone-Yumoto Eva Store") not in normalize_place_name("Hakone")


def test_haversine_distance_m_is_zero_for_identical_points():
    assert haversine_distance_m(35.6762, 139.6503, 35.6762, 139.6503) == 0.0


def test_haversine_distance_m_matches_known_tokyo_kyoto_distance():
    # Tokyo Station to Kyoto Station is ~368km in a straight line.
    distance = haversine_distance_m(35.6812, 139.7671, 34.9858, 135.7581)
    assert 360_000 < distance < 376_000


def test_haversine_distance_m_is_symmetric():
    a = haversine_distance_m(35.6762, 139.6503, 35.0116, 135.7681)
    b = haversine_distance_m(35.0116, 135.7681, 35.6762, 139.6503)
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_location_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.location_matching'`

- [ ] **Step 3: Write the implementation**

```python
# app/location_matching.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_location_matching.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/location_matching.py tests/test_location_matching.py
git commit -m "feat: add place-name normalization and haversine distance helpers"
```

---

### Task 2: `location_matching.py` — `resolve_place`

**Files:**
- Modify: `app/location_matching.py`
- Test: `tests/test_location_matching.py`

**Interfaces:**
- Consumes: `normalize_place_name`, `haversine_distance_m` (Task 1); `app.models.Location`; `sqlmodel.Session`/`select`.
- Produces: `NEW_HUB_SENTINEL: str`; dataclasses `PlaceCandidate(id, name, distance_m)`, `HubOption(id, name)`; `PlaceResolution(place_tier, place_location_id, place_location_name, place_candidates, hub_tier, hub_id, hub_name, hub_options, requires_confirmation)`; `resolve_place(session, place_name, near_hub, lat, lon) -> PlaceResolution`. Used by Task 3 and Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_location_matching.py (append)
from app.location_matching import NEW_HUB_SENTINEL, resolve_place
from app.models import Location


def _add(session, **kwargs):
    loc = Location(**kwargs)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def test_resolve_place_exact_normalized_match_is_auto(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "nishiki market", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id
    assert resolution.requires_confirmation is False


def test_resolve_place_formatting_duplicate_matches_via_normalization(session):
    loc = _add(session, name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77)

    resolution = resolve_place(session, "Surugaya Akihabara (駿河屋秋葉原)", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id


def test_resolve_place_short_name_matches_containing_hub_label(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Tokyo", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == hub.id


def test_resolve_place_does_not_match_hub_when_hub_name_is_only_a_substring_of_new_place(session):
    _add(session, name="Hakone", is_hub=True, lat=35.2323, lon=139.1069)

    resolution = resolve_place(
        session, "Hakone-Yumoto Eva Store", "Hakone", 35.20139, 139.04361
    )

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_similar_name_and_close_distance_is_auto(session):
    # Same real shop, AI phrased the name slightly differently this time.
    # "Ichiran Ramen Shibuya Ten" normalizes to a DIFFERENT string than
    # "Ichiran Ramen Shibuya" (tier 1 must NOT fire here) but scores a high
    # SequenceMatcher ratio (~0.91) against it, so this exercises tier 2
    # specifically -- not tier 1 by coincidence.
    loc = _add(session, name="Ichiran Ramen Shibuya", is_hub=False, lat=35.6590, lon=139.7005)

    resolution = resolve_place(session, "Ichiran Ramen Shibuya Ten", None, 35.6591, 139.7006)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id


def test_resolve_place_close_distance_but_unrelated_name_requires_confirmation(session):
    # Two different shops in the same building: same coordinates, unrelated names.
    _add(session, name="Starbucks Shibuya", is_hub=False, lat=35.6590, lon=139.7005)

    resolution = resolve_place(session, "Pokémon Center Shibuya", None, 35.6590, 139.7005)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None
    assert resolution.requires_confirmation is True


def test_resolve_place_far_distance_returns_ranked_candidate_not_auto_match(session):
    # Kamakura town center vs. the Daibutsu (Kotoku-in), ~2.5km apart.
    kamakura = _add(session, name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)

    resolution = resolve_place(session, "Kotoku-in Daibutsu", None, 35.3166, 139.5360)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None
    assert [c.id for c in resolution.place_candidates] == [kamakura.id]


def test_resolve_place_candidates_default_to_new_place_not_pre_selected(session):
    _add(session, name="Some Other Shop", is_hub=False, lat=35.0, lon=135.0)

    resolution = resolve_place(session, "Unrelated New Shop", None, 35.0001, 135.0001)

    # Close distance (~15m) but unrelated name: shown as a candidate, never auto-picked.
    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_empty_place_name_never_auto_matches(session):
    _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "", None, None, None)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_candidates_capped_and_sorted_by_distance(session):
    for i in range(7):
        _add(session, name=f"Shop {i}", is_hub=False, lat=35.0 + i * 0.001, lon=135.0)

    resolution = resolve_place(session, "New Nearby Shop", None, 35.0, 135.0)

    assert len(resolution.place_candidates) == 5
    distances = [c.distance_m for c in resolution.place_candidates]
    assert distances == sorted(distances)


def test_resolve_place_hub_exact_match_is_auto(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Nikko", "Tokyo / Kanto", 36.7198, 139.6982)

    assert resolution.hub_tier == "auto"
    assert resolution.hub_id == hub.id


def test_resolve_place_hub_no_match_is_ambiguous_with_options(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Nikko", "Somewhere Else", 36.7198, 139.6982)

    assert resolution.hub_tier == "ambiguous"
    assert resolution.hub_id is None
    assert [h.id for h in resolution.hub_options] == [hub.id]


def test_resolve_place_hub_missing_near_hub_is_ambiguous(session):
    resolution = resolve_place(session, "Nikko", None, 36.7198, 139.6982)

    assert resolution.hub_tier == "ambiguous"
    assert resolution.hub_id is None


def test_resolve_place_requires_confirmation_false_when_place_auto_matched(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "Nishiki Market", "Does Not Exist", None, None)

    assert resolution.place_location_id == loc.id
    assert resolution.requires_confirmation is False


def test_resolve_place_requires_confirmation_true_when_hub_ambiguous_even_without_candidates(session):
    resolution = resolve_place(session, "Brand New City Area", "Unknown Hub", None, None)

    assert resolution.place_candidates == []
    assert resolution.hub_tier == "ambiguous"
    assert resolution.requires_confirmation is True


def test_resolve_place_new_hub_sentinel_is_a_non_empty_string():
    assert NEW_HUB_SENTINEL
    assert isinstance(NEW_HUB_SENTINEL, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_location_matching.py -v -k resolve_place`
Expected: FAIL with `ImportError: cannot import name 'resolve_place'`

- [ ] **Step 3: Write the implementation**

```python
# app/location_matching.py (append to the file from Task 1)
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
) -> PlaceResolution:
    normalized_place = normalize_place_name(place_name)
    locations = session.exec(select(Location)).all()

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_location_matching.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add app/location_matching.py tests/test_location_matching.py
git commit -m "feat: add tiered place/hub resolution with distance+similarity gating"
```

---

### Task 3: Single-place confirm flow (`ai_categorize.py` + `ai_chat.html`)

**Files:**
- Modify: `app/routers/ai_categorize.py:48-76` (delete `_find_matching_location`), `:71-77` (delete `_find_hub_by_name`), `:96-132` (`_apply_result_post_processing`), `:244-284` (`_build_ai_chat_context`), `:338-384` (`_resolve_location_and_create_reel`), `:387-407` (`ui_ai_confirm`)
- Modify: `app/templates/partials/ai_chat.html:38-52`
- Modify: `tests/test_ai_categorize.py`, `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `app.location_matching.resolve_place`, `NEW_HUB_SENTINEL`, `PlaceResolution` (Task 2).
- Produces: `_resolve_location_and_create_reel(session, link, place_name, types, note, lat, lon, resolution_location_id, resolution_hub_id="", confidence=None) -> Reel` — new signature, consumed by Task 4 (`ai_multi_categorize.py`) in Task 4's own call site, and by both the `/ui/ai/confirm` endpoint here and tests.

- [ ] **Step 1: Update `_apply_result_post_processing` to use `resolve_place`**

In `app/routers/ai_categorize.py`, delete `_find_matching_location` (lines 48-68) and `_find_hub_by_name` (lines 71-77) entirely, add the import, and replace the body of `_apply_result_post_processing`:

```python
from app.location_matching import NEW_HUB_SENTINEL, resolve_place
```

```python
def _apply_result_post_processing(session: Session, ai_session: AiSession, result: dict) -> Optional[str]:
    """Shared post-AI-call bookkeeping: type filtering, location resolution,
    and the missing-coordinates safety net. Mutates `result` in place and
    returns the auto-matched place location id (None if ambiguous/new).
    DB reads only -- callers own commit()."""
    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    valid_type_keys = get_valid_type_keys(session)
    result["types"] = [t for t in result.get("types", []) if t in valid_type_keys]

    resolution = resolve_place(
        session, result["place_name"], result.get("near_hub"), result.get("lat"), result.get("lon")
    )
    logger.debug("session=%s resolution=%s", ai_session.id, resolution)

    if (
        resolution.place_tier == "ambiguous"
        and result.get("question") is None
        and not result.get("candidates")
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        if resolution.hub_tier == "auto":
            hub = session.get(Location, resolution.hub_id)
            result["lat"] = hub.lat
            result["lon"] = hub.lon

        if result.get("lat") is None or result.get("lon") is None:
            result["question"] = MISSING_COORDINATES_QUESTION

    logger.debug("session=%s final result=%s", ai_session.id, result)
    return resolution.place_location_id
```

This is a behavior-preserving swap for every existing caller of `_apply_result_post_processing` (`_run_turn`, `_persist_categorize_result`, and transitively `/api/ai/categorize`'s `matched_location_id` field) — the return value keeps the same `Optional[str]` meaning (auto-matched place id or `None`), so no other file needs to change for this step. Confirmed against the existing regression tests in `tests/test_ai_categorize.py`:
- `test_categorize_matches_existing_location_case_insensitive`, `test_categorize_still_matches_hub_when_place_name_is_contained_in_hub_label`, `test_categorize_does_not_match_hub_when_hub_name_is_only_a_substring_of_a_new_place`, `test_empty_place_name_does_not_spuriously_match_location`, and all `test_safety_net_*`/`test_persist_categorize_result_*` tests keep passing unmodified — `resolve_place`'s tier-1 hub-containment rule and empty-name guard reproduce the exact same matching decisions these pin.

- [ ] **Step 2: Run the existing test suite to confirm nothing broke yet**

Run: `pytest tests/test_ai_categorize.py tests/test_ai_ui.py tests/test_ai_multi_categorize.py -v`
Expected: Only failures are the ones calling `_resolve_location_and_create_reel` directly and the `/ui/ai/confirm` form tests that pass `matched_location_id` — `_build_ai_chat_context` and `/ui/ai/confirm`'s signature haven't changed yet, so those still fail the same way they will after Step 3-4 too. (If anything else fails, stop and investigate before continuing — it means the drop-in swap above isn't actually behavior-preserving.)

- [ ] **Step 3: Update `_build_ai_chat_context` to expose the full resolution**

```python
def _build_ai_chat_context(
    session: Session, ai_session_id: Optional[str], link: str, notice: Optional[str] = None
) -> dict:
    history: list[dict] = []
    latest_result: Optional[dict] = None

    if ai_session_id:
        messages = session.exec(
            select(AiMessage)
            .where(AiMessage.session_id == ai_session_id)
            .order_by(AiMessage.created_at)
        ).all()
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "text": m.content})
            else:
                result = json.loads(m.content)
                history.append({"role": "assistant", "result": result})
                latest_result = result

    resolution = (
        resolve_place(
            session,
            latest_result["place_name"],
            latest_result.get("near_hub"),
            latest_result.get("lat"),
            latest_result.get("lon"),
        )
        if latest_result is not None
        else None
    )
    can_confirm = (
        latest_result is not None
        and latest_result.get("question") is None
        and not latest_result.get("candidates")
    )

    return {
        "session_id": ai_session_id or "",
        "link": link or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "resolution": resolution,
        "taxonomy": get_taxonomy(session),
        "notice": notice,
    }
```

- [ ] **Step 4: Update `_resolve_location_and_create_reel`'s signature and body**

```python
def _resolve_location_and_create_reel(
    session: Session,
    link: str,
    place_name: str,
    types: list[str],
    note: str,
    lat,
    lon,
    resolution_location_id: str,
    resolution_hub_id: str = "",
    confidence: Optional[str] = None,
) -> Reel:
    if resolution_location_id:
        location_id = resolution_location_id
    else:
        if not lat or not lon:
            raise HTTPException(
                status_code=400, detail="lat/lon are required to create a new location"
            )
        if not resolution_hub_id:
            raise HTTPException(
                status_code=400, detail="a hub choice is required to create a new location"
            )

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

    reel = Reel(link=link, location_id=location_id, note=note or None)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return reel
```

- [ ] **Step 5: Update `ui_ai_confirm`'s form fields and call site**

```python
@ui_router.post("/confirm")
def ui_ai_confirm(
    request: Request,
    session_id: str = Form(...),
    link: str = Form(...),
    place_name: str = Form(...),
    types: list[str] = Form([]),
    note: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    resolution_location_id: str = Form(""),
    resolution_hub_id: str = Form(""),
    confidence: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    _resolve_location_and_create_reel(
        session, link, place_name, types, note, lat, lon, resolution_location_id, resolution_hub_id, confidence
    )

    stale_ai_session = session.get(AiSession, session_id)
    if stale_ai_session is not None:
        for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
            session.delete(msg)
        session.delete(stale_ai_session)
        session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

(Body unchanged below the `_resolve_location_and_create_reel` call — only the call site and the parameter list above it changed.)

- [ ] **Step 6: Update `ai_chat.html`'s confirm block**

Replace lines 38-52 of `app/templates/partials/ai_chat.html`:

```html
{% if can_confirm %}
<form hx-post="/ui/ai/confirm" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-confirm-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    <input type="hidden" name="link" value="{{ link }}">
    <input type="hidden" name="place_name" value="{{ latest_result.place_name }}">
    {% for t in latest_result.types %}<input type="hidden" name="types" value="{{ t }}">{% endfor %}
    <input type="hidden" name="note" value="{{ latest_result.note }}">
    <input type="hidden" name="lat" value="{{ latest_result.lat if latest_result.lat is not none else '' }}">
    <input type="hidden" name="lon" value="{{ latest_result.lon if latest_result.lon is not none else '' }}">
    <input type="hidden" name="confidence" value="{{ latest_result.confidence or '' }}">

    {% if not resolution.requires_confirmation %}
        {% if resolution.place_tier == 'auto' %}
        <p class="resolution-info">Verrà salvato sotto: {{ resolution.place_location_name }}</p>
        {% else %}
        <p class="resolution-info">Nuovo posto satellite di {{ resolution.hub_name }}</p>
        {% endif %}
        <input type="hidden" name="resolution_location_id" value="{{ resolution.place_location_id or '' }}">
        <input type="hidden" name="resolution_hub_id" value="{{ resolution.hub_id or '' }}">
    {% else %}
        <div class="resolution-picker">
            {% if resolution.place_candidates %}
            <label>Posto:
                <select name="resolution_location_id">
                    <option value="">È un posto nuovo</option>
                    {% for c in resolution.place_candidates %}
                    <option value="{{ c.id }}">{{ c.name }} ({{ c.distance_m }}m)</option>
                    {% endfor %}
                </select>
            </label>
            {% else %}
            <input type="hidden" name="resolution_location_id" value="">
            {% endif %}

            {% if resolution.hub_tier == 'ambiguous' %}
            <label>Hub (se è un posto nuovo):
                <select name="resolution_hub_id">
                    <option value="">— scegli —</option>
                    {% for h in resolution.hub_options %}
                    <option value="{{ h.id }}">{{ h.name }}</option>
                    {% endfor %}
                    <option value="__new_hub__">Crea nuovo hub</option>
                </select>
            </label>
            {% else %}
            <input type="hidden" name="resolution_hub_id" value="{{ resolution.hub_id or '' }}">
            {% endif %}
        </div>
    {% endif %}

    <button type="submit">Conferma e salva</button>
</form>
{% endif %}
```

- [ ] **Step 7: Update `tests/test_ai_categorize.py`'s direct `_resolve_location_and_create_reel` calls**

Replace the four existing calls and add two new tests:

```python
import pytest
from fastapi import HTTPException

from app.location_matching import NEW_HUB_SENTINEL


def test_resolve_location_and_create_reel_uses_matched_location(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session, "https://instagram.com/reel/abc", "Tokyo / Kanto", ["food"], "Ramen chain", "", "", hub.id,
    )

    assert reel.location_id == hub.id
    assert session.exec(select(Location)).all() == [hub]


def test_resolve_location_and_create_reel_creates_new_satellite_under_hub(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="nature", label="Natura", icon="🌸"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session, "https://instagram.com/reel/nikko", "Nikko", ["nature"], "Shrine town",
        "36.7198", "139.6982", "", hub.id,
    )

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert reel.location_id == satellite.id


def test_resolve_location_and_create_reel_creates_new_hub_when_sentinel_chosen(session):
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

    reel = _resolve_location_and_create_reel(
        session, "https://instagram.com/reel/sapporo", "Sapporo Ramen Alley", ["food"], "Ramen alley",
        "43.0618", "141.3545", "", NEW_HUB_SENTINEL,
    )

    location = session.exec(select(Location).where(Location.name == "Sapporo Ramen Alley")).first()
    assert location.is_hub is True
    assert location.parent_id is None
    assert reel.location_id == location.id


def test_resolve_location_and_create_reel_requires_hub_choice_for_new_location(session):
    with pytest.raises(HTTPException) as exc_info:
        _resolve_location_and_create_reel(
            session, "https://instagram.com/reel/x", "Nowhere", [], "", "1.0", "1.0", "", "",
        )

    assert exc_info.value.status_code == 400


def test_resolve_location_and_create_reel_stores_confidence_on_new_location(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    _resolve_location_and_create_reel(
        session, "https://instagram.com/reel/mystery", "Mystery Alley", [], "",
        "35.7", "139.7", "", hub.id, "low",
    )

    location = session.exec(select(Location).where(Location.name == "Mystery Alley")).first()
    assert location.geocode_confidence == "low"


def test_resolve_location_and_create_reel_leaves_matched_location_confidence_untouched(session):
    hub = Location(
        name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503, geocode_confidence="high"
    )
    session.add(hub)
    session.commit()
    session.refresh(hub)

    _resolve_location_and_create_reel(
        session, "https://instagram.com/reel/abc", "Tokyo / Kanto", [], "", "", "", hub.id, "", "low",
    )

    session.refresh(hub)
    assert hub.geocode_confidence == "high"
```

Delete the old `test_resolve_location_and_create_reel_stores_confidence_on_new_location` and `test_resolve_location_and_create_reel_leaves_matched_location_confidence_untouched` bodies (lines 558-594 of the original file) and replace with the versions above — same test names, new call signature.

- [ ] **Step 8: Update `tests/test_ai_ui.py`'s `/ui/ai/confirm` payloads**

```python
from app.location_matching import NEW_HUB_SENTINEL


def test_ui_ai_confirm_with_matched_location_creates_reel_on_existing_location(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "resolution_location_id": hub.id,
        },
    )
    assert response.status_code == 200

    reels = session.exec(select(Reel)).all()
    assert len(reels) == 1
    assert reels[0].location_id == hub.id
    assert session.exec(select(Location)).all() == [hub]


def test_ui_ai_confirm_creates_satellite_under_matching_hub(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="nature", label="Natura", icon="🌸"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/nikko",
            "place_name": "Nikko",
            "types": ["nature"],
            "note": "Shrine town",
            "lat": "36.7198",
            "lon": "139.6982",
            "resolution_location_id": "",
            "resolution_hub_id": hub.id,
        },
    )
    assert response.status_code == 200

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert satellite.lat == 36.7198


def test_ui_ai_confirm_creates_new_hub_when_sentinel_chosen(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "resolution_location_id": "",
            "resolution_hub_id": NEW_HUB_SENTINEL,
        },
    )
    assert response.status_code == 200

    location = session.exec(select(Location).where(Location.name == "Sapporo Ramen Alley")).first()
    assert location is not None
    assert location.is_hub is True
    assert location.parent_id is None


def test_ui_ai_confirm_without_any_hub_choice_returns_400(client, session):
    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "types": [],
            "note": "",
            "lat": "43.0618",
            "lon": "141.3545",
            "resolution_location_id": "",
            "resolution_hub_id": "",
        },
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_confirm_stores_confidence_on_new_location(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "resolution_location_id": "",
            "resolution_hub_id": NEW_HUB_SENTINEL,
            "confidence": "low",
        },
    )
    assert response.status_code == 200

    location = session.exec(select(Location).where(Location.name == "Sapporo Ramen Alley")).first()
    assert location.geocode_confidence == "low"


def test_ui_ai_confirm_rejects_invalid_link(client, session):
    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "javascript:alert(1)",
            "place_name": "Somewhere",
            "types": [],
            "note": "",
            "lat": "1.0",
            "lon": "1.0",
            "resolution_location_id": "",
            "resolution_hub_id": NEW_HUB_SENTINEL,
        },
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_confirm_resets_panel_and_updates_reel_list(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "resolution_location_id": hub.id,
        },
    )
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert "Conferma e salva" not in response.text
    assert 'hx-swap-oob="innerHTML:#reel-list"' in response.text
    assert "https://instagram.com/reel/abc" in response.text
    assert 'hx-swap-oob="innerHTML:#map-container">' in response.text
    assert 'hx-swap-oob="innerHTML:#reel-add-form-panel"' in response.text
    assert response.headers["hx-trigger"] == "reel-saved"


def test_ui_ai_confirm_cleans_up_the_ai_session(client, session, monkeypatch):
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

    monkeypatch.setattr(
        ai_client, "detect_places", lambda message: {"is_multi_place": False, "place_names": None}
    )
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Sapporo Ramen Alley",
            "near_hub": None,
            "types": ["food"],
            "note": "Ramen alley",
            "confidence": "high",
            "question": None,
            "lat": 43.0618,
            "lon": 141.3545,
        },
    )
    client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/sapporo", "message": "Ramen alley a Sapporo"},
    )
    ai_session_id = session.exec(select(AiSession)).first().id

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": ai_session_id,
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "resolution_location_id": "",
            "resolution_hub_id": NEW_HUB_SENTINEL,
        },
    )
    assert response.status_code == 200
    assert session.exec(select(AiSession).where(AiSession.id == ai_session_id)).first() is None
    assert session.exec(select(AiMessage).where(AiMessage.session_id == ai_session_id)).all() == []
```

Delete the old `test_ui_ai_confirm_creates_new_hub_when_no_hub_matches` (replaced by `test_ui_ai_confirm_creates_new_hub_when_sentinel_chosen` above, which asserts the same resulting state but via the new explicit-choice contract instead of relying on a silent fallback) and add `test_ui_ai_confirm_without_any_hub_choice_returns_400` as a brand-new test (the Review Focus item for this task).

- [ ] **Step 9: Run the full AI test suite to verify everything passes**

Run: `pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: PASS (every test in both files, including the ones left untouched since Step 2 confirmed the swap was behavior-preserving for them)

- [ ] **Step 10: Commit**

```bash
git add app/routers/ai_categorize.py app/templates/partials/ai_chat.html tests/test_ai_categorize.py tests/test_ai_ui.py
git commit -m "feat: wire single-place AI confirm flow to tiered location resolution"
```

---

### Task 4: Multi-place confirm flow (`ai_multi_categorize.py` + `ai_chat_multi.html` + JS)

**Files:**
- Modify: `app/routers/ai_multi_categorize.py:12-19` (import), `:54-93` (`_build_multi_context`), `:148-176` (`ui_ai_multi_confirm`)
- Modify: `app/templates/partials/ai_chat_multi.html:1-21`
- Create: `app/static/js/ai-multi-resolution.js`
- Modify: `app/templates/base.html` (add script include)
- Modify: `tests/test_ai_multi_categorize.py`

**Interfaces:**
- Consumes: `resolve_place`, `NEW_HUB_SENTINEL` (Task 2); `_resolve_location_and_create_reel` new signature (Task 3).

- [ ] **Step 1: Update `_build_multi_context` to compute and embed a resolution per row**

In `app/routers/ai_multi_categorize.py`, change the import line:

```python
from app.location_matching import NEW_HUB_SENTINEL, resolve_place
from app.routers.ai_categorize import (
    _build_ai_chat_context,
    _categorize_new_session_message,
    _persist_categorize_result,
    _resolve_location_and_create_reel,
    _run_turn,
)
```

(Drops the now-deleted `_find_matching_location` import.)

Replace `_build_multi_context`:

```python
def _build_multi_context(session: Session, session_ids: list[str], link: str) -> dict:
    seen: set[str] = set()
    session_ids = [sid for sid in session_ids if not (sid in seen or seen.add(sid))]

    rows = []
    for session_id in session_ids:
        result = _read_latest_result(session, session_id)
        if result is None:
            continue
        resolution = resolve_place(
            session, result.get("place_name", ""), result.get("near_hub"), result.get("lat"), result.get("lon")
        )
        resolved = result.get("question") is None
        place_payload = {
            "place_name": result.get("place_name", ""),
            "types": result.get("types", []),
            "note": result.get("note", ""),
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "resolution_location_id": resolution.place_location_id or "",
            "resolution_hub_id": resolution.hub_id or "",
            "confidence": result.get("confidence"),
        }
        rows.append(
            {
                "session_id": session_id,
                "result": result,
                "resolved": resolved,
                "resolution": resolution,
                "place_json": json.dumps(place_payload),
            }
        )

    return {
        "link": link or "",
        "session_ids": session_ids,
        "rows": rows,
        "taxonomy": get_taxonomy(session),
    }
```

- [ ] **Step 2: Update `ui_ai_multi_confirm` to read the new keys**

```python
@router.post("/confirm")
def ui_ai_multi_confirm(
    request: Request,
    link: str = Form(...),
    session_ids: list[str] = Form([]),
    place_json: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    for raw in place_json:
        try:
            place = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry")
            continue
        _resolve_location_and_create_reel(
            session,
            link,
            place["place_name"],
            place.get("types", []),
            place.get("note", ""),
            place.get("lat"),
            place.get("lon"),
            place.get("resolution_location_id", ""),
            place.get("resolution_hub_id", ""),
            place.get("confidence"),
        )

    for session_id in session_ids:
        stale_ai_session = session.get(AiSession, session_id)
        if stale_ai_session is not None:
            for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
                session.delete(msg)
            session.delete(stale_ai_session)
            session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

- [ ] **Step 3: Add the JS helper that patches a row's embedded `place_json`**

```javascript
// app/static/js/ai-multi-resolution.js
window.patchMultiPlaceResolution = function (selectEl, key) {
    const row = selectEl.closest(".multi-place-row");
    const hiddenInput = row.querySelector('input[name="place_json"]');
    const data = JSON.parse(hiddenInput.value);
    data[key] = selectEl.value;
    hiddenInput.value = JSON.stringify(data);
};
```

- [ ] **Step 4: Include the new script in `base.html`**

Add one line next to the other `<script src="/static/js/...">` includes (after `reel-list.js`):

```html
    <script src="/static/js/ai-multi-resolution.js"></script>
```

- [ ] **Step 5: Update `ai_chat_multi.html`'s resolved-row block**

Replace lines 6-17 of `app/templates/partials/ai_chat_multi.html`:

```html
    {% for row in rows %}
        {% if row.resolved %}
        <label class="multi-place-row">
            <input type="checkbox" name="place_json" value='{{ row.place_json }}' checked>
            <span class="multi-place-row-content">
                <strong>{{ row.result.place_name }}</strong>
                <span class="types">{% for t in row.result.types %}{{ taxonomy[t].icon }} {{ taxonomy[t].label }} {% endfor %}</span>
                {% if row.result.note %}<span class="note">{{ row.result.note }}</span>{% endif %}

                {% if not row.resolution.requires_confirmation %}
                    {% if row.resolution.place_tier == 'auto' %}
                    <span class="resolution-info">Verrà salvato sotto: {{ row.resolution.place_location_name }}</span>
                    {% else %}
                    <span class="resolution-info">Nuovo posto satellite di {{ row.resolution.hub_name }}</span>
                    {% endif %}
                {% else %}
                    {% if row.resolution.place_candidates %}
                    <select onchange="patchMultiPlaceResolution(this, 'resolution_location_id')">
                        <option value="">È un posto nuovo</option>
                        {% for c in row.resolution.place_candidates %}
                        <option value="{{ c.id }}">{{ c.name }} ({{ c.distance_m }}m)</option>
                        {% endfor %}
                    </select>
                    {% endif %}
                    {% if row.resolution.hub_tier == 'ambiguous' %}
                    <select onchange="patchMultiPlaceResolution(this, 'resolution_hub_id')">
                        <option value="">— scegli hub —</option>
                        {% for h in row.resolution.hub_options %}
                        <option value="{{ h.id }}">{{ h.name }}</option>
                        {% endfor %}
                        <option value="__new_hub__">Crea nuovo hub</option>
                    </select>
                    {% endif %}
                {% endif %}
            </span>
        </label>
        {% endif %}
    {% endfor %}
```

- [ ] **Step 6: Update `tests/test_ai_multi_categorize.py`'s hand-built `place_json` payloads**

```python
def test_ui_ai_multi_confirm_creates_reel_per_checked_place_sharing_the_link(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.add(Category(key="culture", label="Cultura", icon="⛩️"))
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "types": ["culture"],
        "note": "Torii gates", "lat": None, "lon": None,
        "resolution_location_id": hub.id, "resolution_hub_id": "",
    })
    place_two = json.dumps({
        "place_name": "Kiyomizu-dera", "types": ["culture"],
        "note": "Historic temple", "lat": 34.9949, "lon": 135.785,
        "resolution_location_id": "", "resolution_hub_id": hub.id,
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [place_one, place_two],
        },
    )

    assert response.status_code == 200
    reels = session.exec(select(Reel)).all()
    assert len(reels) == 2
    assert {r.link for r in reels} == {"https://instagram.com/reel/kyoto10"}
    kiyomizu = session.exec(select(Location).where(Location.name == "Kiyomizu-dera")).first()
    assert {r.location_id for r in reels} == {hub.id, kiyomizu.id}
    assert kiyomizu.geocode_confidence is None


def test_ui_ai_multi_confirm_stores_confidence_on_newly_created_location(client, session):
    place = json.dumps({
        "place_name": "Mystery Alley", "types": [],
        "note": "", "lat": 35.7, "lon": 139.7,
        "resolution_location_id": "", "resolution_hub_id": "__new_hub__", "confidence": "low",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1"],
            "place_json": [place],
        },
    )

    assert response.status_code == 200
    location = session.exec(select(Location).where(Location.name == "Mystery Alley")).first()
    assert location.geocode_confidence == "low"


def test_ui_ai_multi_confirm_only_creates_reels_for_checked_places(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "types": [],
        "note": "", "lat": None, "lon": None,
        "resolution_location_id": hub.id, "resolution_hub_id": "",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [place_one],
        },
    )

    assert response.status_code == 200
    assert len(session.exec(select(Reel)).all()) == 1
```

The remaining tests in this file (`test_start_multi_place_batch_*`, `test_ui_ai_message_routes_to_multi_place_batch_when_detected`, `test_ui_ai_message_falls_back_to_single_place_when_detect_places_fails`, `test_multi_place_row_shows_clarify_form_for_unresolved_place`, `test_ui_ai_multi_message_advances_only_the_clarified_session`, `test_ui_ai_multi_confirm_cleans_up_all_sessions_in_the_batch`, `test_ui_ai_multi_confirm_with_no_checked_places_creates_nothing`, `test_ui_ai_multi_confirm_cleans_up_unchecked_sessions_too`) don't construct `place_json` by hand with the old `matched_location_id`/`near_hub` keys — they either extract whatever `place_json` the server actually rendered (via regex) or don't inspect its contents at all, so they need no changes.

- [ ] **Step 7: Run the multi-place test suite to verify everything passes**

Run: `pytest tests/test_ai_multi_categorize.py -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add app/routers/ai_multi_categorize.py app/templates/partials/ai_chat_multi.html app/templates/base.html app/static/js/ai-multi-resolution.js tests/test_ai_multi_categorize.py
git commit -m "feat: wire multi-place AI confirm flow to tiered location resolution"
```

---

### Task 5: Full regression pass and cleanup

**Files:** none new — verification only, plus removing any now-dead code found along the way.

- [ ] **Step 1: Run the entire test suite**

Run: `pytest`
Expected: all tests pass, zero errors/warnings in the output.

- [ ] **Step 2: Grep for any remaining reference to the removed functions**

Run: `grep -rn "_find_matching_location\|_find_hub_by_name" app/ tests/`
Expected: no output (both fully removed in Task 3).

- [ ] **Step 3: Grep for any remaining reference to the old `matched_location_id` form field or `near_hub`-as-hidden-input in templates**

Run: `grep -rn "matched_location_id" app/templates/ app/routers/`
Expected: no output.

- [ ] **Step 4: Manually smoke-test the ambiguous path once with the dev server**

Start the app locally (`uvicorn app.main:app --reload` or however the project is normally run — see `README.md`), open the AI add-reel panel, and submit a caption describing a place within ~2km of an existing saved location but with an unrelated name (e.g. if "Shibuya" exists, describe "Pokémon Center Shibuya" with no other distinguishing hub). Confirm the candidate `<select>` and hub `<select>` actually render and that picking "È un posto nuovo" + an existing hub creates a new satellite without disturbing the existing "Shibuya" location's name/coordinates. This is UI behavior Playwright/TestClient assertions don't fully exercise (real browser `<select>` interaction) — flag to the user if this step can't be run in this environment and ask them to verify it live instead.

- [ ] **Step 5: Final commit (only if Step 2-4 required any fixes)**

```bash
git add -A
git commit -m "chore: clean up dead location-matching code after AI resolution rewrite"
```

(Skip this step entirely if Steps 1-4 found nothing to fix — don't create an empty commit.)

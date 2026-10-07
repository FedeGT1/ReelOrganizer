import html
import json
import re
import time

from sqlmodel import select

from app.ai import client as ai_client
from app.location_matching import NEW_HUB_SENTINEL
from app.models import AiSession, Category, Location, Reel


def _with_new_hub_choice(place_json: str) -> str:
    """Patch a server-rendered place_json string the way the browser's
    patchMultiPlaceResolution() would, picking "Crea nuovo hub" -- needed
    whenever no hub exists/matches, since the resolver requires an explicit
    hub choice before creating a brand-new location."""
    data = json.loads(place_json)
    data["resolution_hub_id"] = NEW_HUB_SENTINEL
    return json.dumps(data)


def test_start_multi_place_batch_pairs_results_correctly_despite_out_of_order_completion(
    client, session, monkeypatch
):
    # Regression guard for running categorize() calls in parallel: they can
    # finish in any order, so the batch must attach each result to the
    # place it was actually asked about, not to whichever call happened to
    # return first.
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {
            "is_multi_place": True,
            "place_names": ["Slow Place", "Medium Place", "Fast Place"],
        },
    )

    def fake_categorize(hub_names, categories, messages):
        text = messages[0]["content"]
        if "Slow Place" in text:
            time.sleep(0.3)
            name = "Slow Place"
        elif "Medium Place" in text:
            time.sleep(0.15)
            name = "Medium Place"
        else:
            name = "Fast Place"
        return {
            "place_name": name, "near_hub": None, "types": [], "note": "",
            "confidence": "high", "question": None, "lat": 35.0, "lon": 135.0,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/order-test", "message": "3 posti"},
    )

    assert response.status_code == 200
    place_jsons = [
        html.unescape(m) for m in re.findall(r"name=\"place_json\" value='([^']+)'", response.text)
    ]
    place_names_in_order = [json.loads(pj)["place_name"] for pj in place_jsons]
    assert place_names_in_order == ["Slow Place", "Medium Place", "Fast Place"]


def test_start_multi_place_batch_runs_categorize_calls_concurrently(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {
            "is_multi_place": True,
            "place_names": ["Posto 1", "Posto 2", "Posto 3", "Posto 4"],
        },
    )

    def fake_categorize(hub_names, categories, messages):
        time.sleep(0.2)
        return {
            "place_name": "x", "near_hub": None, "types": [], "note": "",
            "confidence": "high", "question": None, "lat": 35.0, "lon": 135.0,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    start = time.monotonic()
    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/speed-test", "message": "4 posti"},
    )
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    # 4 calls x 0.2s each: sequential would take >=0.8s; concurrent should
    # take close to one call's duration. Generous ceiling to avoid flakiness.
    assert elapsed < 0.6


def test_ui_ai_message_routes_to_multi_place_batch_when_detected(client, session, monkeypatch):
    session.add(Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {
            "is_multi_place": True,
            "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera"],
        },
    )

    results = iter(
        [
            {
                "place_name": "Fushimi Inari Taisha",
                "near_hub": "Kyoto - Osaka / Kansai",
                "types": ["culture"],
                "note": "Famous torii gates",
                "confidence": "high",
                "question": None,
                "lat": None,
                "lon": None,
            },
            {
                "place_name": "Kiyomizu-dera",
                "near_hub": "Kyoto - Osaka / Kansai",
                "types": ["culture"],
                "note": "Historic wooden temple",
                "confidence": "high",
                "question": None,
                "lat": None,
                "lon": None,
            },
        ]
    )
    monkeypatch.setattr(
        ai_client, "categorize", lambda hub_names, categories, messages: next(results)
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto10", "message": "10 posti a Kyoto"},
    )

    assert response.status_code == 200
    assert "Fushimi Inari Taisha" in response.text
    assert "Kiyomizu-dera" in response.text
    assert response.text.count('name="place_json"') == 2
    assert len(session.exec(select(AiSession)).all()) == 2


def test_ui_ai_message_falls_back_to_single_place_when_detect_places_fails(client, session, monkeypatch):
    def boom(message):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_client, "detect_places", boom)
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": None,
            "types": ["food"],
            "note": "Ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.0,
            "lon": 135.0,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Ramen a Tokyo"},
    )

    assert response.status_code == 200
    assert "Ichiran Ramen" in response.text
    assert len(session.exec(select(AiSession)).all()) == 1


def test_multi_place_row_shows_clarify_form_for_unresolved_place(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Posto Misterioso", "Nishiki Market"]},
    )

    results = iter(
        [
            {
                "place_name": "Posto Misterioso",
                "near_hub": None,
                "types": [],
                "note": "",
                "confidence": "low",
                "question": None,
                "lat": None,
                "lon": None,
            },
            {
                "place_name": "Nishiki Market",
                "near_hub": None,
                "types": ["food"],
                "note": "Historic market",
                "confidence": "high",
                "question": None,
                "lat": 35.005,
                "lon": 135.765,
            },
        ]
    )
    monkeypatch.setattr(
        ai_client, "categorize", lambda hub_names, categories, messages: next(results)
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto2", "message": "2 posti a Kyoto"},
    )

    assert response.status_code == 200
    assert "coordinate" in response.text.lower()
    assert "Posto Misterioso" in response.text
    assert 'name="clarify_session_id"' in response.text
    assert response.text.count('name="place_json"') == 1


def test_ui_ai_multi_message_advances_only_the_clarified_session(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Posto Misterioso", "Nishiki Market"]},
    )
    results = iter(
        [
            {
                "place_name": "Posto Misterioso", "near_hub": None, "types": [], "note": "",
                "confidence": "low", "question": None, "lat": None, "lon": None,
            },
            {
                "place_name": "Nishiki Market", "near_hub": None, "types": ["food"], "note": "Historic market",
                "confidence": "high", "question": None, "lat": 35.005, "lon": 135.765,
            },
        ]
    )
    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: next(results))

    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto2", "message": "2 posti a Kyoto"},
    )
    assert len(session.exec(select(AiSession)).all()) == 2

    clarify_session_id = re.search(r'name="clarify_session_id" value="([^"]+)"', first.text).group(1)
    all_session_ids = re.findall(r'name="session_ids" value="([^"]+)"', first.text)

    session.add(Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681))
    session.commit()
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Posto Misterioso", "near_hub": "Kyoto - Osaka / Kansai", "types": ["culture"],
            "note": "Ora chiaro", "confidence": "medium", "question": None, "lat": None, "lon": None,
        },
    )

    second = client.post(
        "/ui/ai/multi/message",
        data={
            "link": "https://instagram.com/reel/kyoto2",
            "session_ids": all_session_ids,
            "clarify_session_id": clarify_session_id,
            "clarify_text": "e' vicino ad Arashiyama",
        },
    )

    assert second.status_code == 200
    assert second.text.count('name="place_json"') == 2


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


def test_ui_ai_multi_confirm_warns_when_link_already_saved_before_batch(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/kyoto10", location_id=hub.id, note="Già visto"))
    session.commit()

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "types": [],
        "note": "", "lat": None, "lon": None,
        "resolution_location_id": hub.id, "resolution_hub_id": "",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1"],
            "place_json": [place_one],
        },
    )

    assert response.status_code == 200
    assert "Salva comunque" in response.text
    reels = session.exec(select(Reel)).all()
    assert len(reels) == 1


def test_ui_ai_multi_confirm_duplicate_true_saves_anyway(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/kyoto10", location_id=hub.id))
    session.commit()

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "types": [],
        "note": "", "lat": None, "lon": None,
        "resolution_location_id": hub.id, "resolution_hub_id": "",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1"],
            "place_json": [place_one],
            "confirm_duplicate": "true",
        },
    )

    assert response.status_code == 200
    reels = session.exec(select(Reel)).all()
    assert len(reels) == 2


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


def test_ui_ai_multi_confirm_validates_all_places_before_creating_any(client, session):
    # Regression guard: the old loop called _resolve_location_and_create_reel
    # one place at a time, and that function commits internally. If place #1
    # was valid and got created+committed, then place #2 in the SAME batch
    # failed validation (missing hub choice), the 400 would leave place #1's
    # reel sitting in the DB -- a resubmission of the fixed batch would then
    # duplicate it. The whole batch must be validated up front so either
    # nothing is created or everything is.
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "types": [],
        "note": "", "lat": None, "lon": None,
        "resolution_location_id": hub.id, "resolution_hub_id": "",
    })
    # Missing hub choice: no resolution_location_id AND no resolution_hub_id,
    # even though lat/lon are present.
    place_two = json.dumps({
        "place_name": "Kiyomizu-dera", "types": [],
        "note": "", "lat": 34.9949, "lon": 135.785,
        "resolution_location_id": "", "resolution_hub_id": "",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [place_one, place_two],
        },
    )

    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_multi_confirm_cleans_up_all_sessions_in_the_batch(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera"]},
    )
    results = iter([
        {"place_name": "Fushimi Inari Taisha", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.967, "lon": 135.772},
        {"place_name": "Kiyomizu-dera", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.9949, "lon": 135.785},
    ])
    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: next(results))

    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto10", "message": "2 posti a Kyoto"},
    )
    session_ids = re.findall(r'name="session_ids" value="([^"]+)"', first.text)
    place_jsons = [
        html.unescape(m) for m in re.findall(r"name=\"place_json\" value='([^']+)'", first.text)
    ]
    assert len(session_ids) == 2
    assert len(place_jsons) == 2

    # No hub exists/matches for either place, so the UI's hub picker would
    # require a choice before submitting; simulate the user picking "Crea
    # nuovo hub" for both, same as patchMultiPlaceResolution would write.
    place_jsons = [_with_new_hub_choice(pj) for pj in place_jsons]

    response = client.post(
        "/ui/ai/multi/confirm",
        data={"link": "https://instagram.com/reel/kyoto10", "session_ids": session_ids, "place_json": place_jsons},
    )

    assert response.status_code == 200
    assert session.exec(select(AiSession)).all() == []


def test_ui_ai_multi_confirm_with_no_checked_places_creates_nothing(client, session):
    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [],
        },
    )

    assert response.status_code == 200
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_multi_confirm_cleans_up_unchecked_sessions_too(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera"]},
    )
    results = iter([
        {"place_name": "Fushimi Inari Taisha", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.967, "lon": 135.772},
        {"place_name": "Kiyomizu-dera", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.9949, "lon": 135.785},
    ])
    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: next(results))

    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto10", "message": "2 posti a Kyoto"},
    )
    session_ids = re.findall(r'name="session_ids" value="([^"]+)"', first.text)
    place_jsons = [
        html.unescape(m) for m in re.findall(r"name=\"place_json\" value='([^']+)'", first.text)
    ]
    assert len(session_ids) == 2
    assert len(place_jsons) == 2

    # No hub exists/matches for either place, so the UI's hub picker would
    # require a choice before submitting; simulate the user picking "Crea
    # nuovo hub", same as patchMultiPlaceResolution would write.
    place_jsons = [_with_new_hub_choice(pj) for pj in place_jsons]

    # Confirm with only ONE of the two places checked (simulating the user
    # unchecking the other) — both sessions must still be cleaned up.
    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": session_ids,
            "place_json": [place_jsons[0]],  # only the first place checked
        },
    )

    assert response.status_code == 200
    assert len(session.exec(select(Reel)).all()) == 1
    assert session.exec(select(AiSession)).all() == []

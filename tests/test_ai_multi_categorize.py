import html
import json
import re

from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiSession, Category, Location, Reel


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
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#35496B"))
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "near_hub": "", "types": ["culture"],
        "note": "Torii gates", "lat": None, "lon": None, "matched_location_id": hub.id,
    })
    place_two = json.dumps({
        "place_name": "Kiyomizu-dera", "near_hub": "Kyoto - Osaka / Kansai", "types": ["culture"],
        "note": "Historic temple", "lat": 34.9949, "lon": 135.785, "matched_location_id": "",
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


def test_ui_ai_multi_confirm_only_creates_reels_for_checked_places(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "near_hub": "", "types": [],
        "note": "", "lat": None, "lon": None, "matched_location_id": hub.id,
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

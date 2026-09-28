import re

from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiSession, Location


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

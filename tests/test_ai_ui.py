from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiSession, Location


def test_ui_ai_panel_renders_empty_state(client):
    response = client.get("/ui/ai/panel")
    assert response.status_code == 200
    assert 'name="link"' in response.text
    assert 'name="message"' in response.text


def test_ui_ai_message_first_turn_creates_session_and_shows_proposal(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Ramen a Tokyo"},
    )
    assert response.status_code == 200
    assert "Ichiran Ramen" in response.text
    assert session.exec(select(AiSession)).first() is not None


def test_ui_ai_message_continues_existing_session(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
            "place_name": "?",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "In che citta si trova?",
            "lat": None,
            "lon": None,
        },
    )
    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Un tempio"},
    )
    assert "In che citta si trova?" in first.text

    session_id = session.exec(select(AiSession)).first().id

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
            "place_name": "Nikko",
            "near_hub": None,
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
            "lat": 36.7198,
            "lon": 139.6982,
        },
    )
    second = client.post(
        "/ui/ai/message",
        data={"session_id": session_id, "link": "https://instagram.com/reel/abc", "message": "E' Nikko"},
    )
    assert second.status_code == 200
    assert "Nikko" in second.text


def test_ui_ai_message_rejects_invalid_link_on_first_turn(client, session):
    response = client.post(
        "/ui/ai/message",
        data={"link": "javascript:alert(1)", "message": "Qualcosa"},
    )
    assert response.status_code == 400
    assert session.exec(select(AiSession)).all() == []


def test_ui_ai_message_forces_question_when_new_location_missing_coordinates(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
            "place_name": "Mystery Alley",
            "near_hub": None,
            "types": ["food"],
            "note": "Some alley",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/xyz", "message": "Un vicolo di street food"},
    )
    assert response.status_code == 200
    assert "coordinate" in response.text.lower()

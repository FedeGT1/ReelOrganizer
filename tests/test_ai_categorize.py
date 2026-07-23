import json

from app.ai import client as ai_client
from app.models import Location


def test_categorize_creates_session_and_returns_proposal(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()

    def fake_categorize(hub_names, messages):
        return {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food", "not-a-real-type"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    response = client.post("/api/ai/categorize", json={"message": "Ramen a Tokyo, link X"})
    assert response.status_code == 200
    data = response.json()
    assert data["place_name"] == "Ichiran Ramen"
    assert data["types"] == ["food"]
    assert data["session_id"]
    assert data["matched_location_id"] is None


def test_categorize_continues_existing_session(client, session, monkeypatch):
    def fake_categorize(hub_names, messages):
        # Full session history: first user turn, first assistant (question)
        # turn, second user turn — never windowed (spec §5.3: the model must
        # see the entire conversation, not just the last exchange).
        assert len(messages) == 3
        return {
            "place_name": "Nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
        }

    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, messages: {
        "place_name": "?",
        "near_hub": None,
        "types": [],
        "note": "",
        "confidence": "low",
        "question": "Che citta' e'?",
    })
    first = client.post("/api/ai/categorize", json={"message": "Un tempio in montagna"})
    session_id = first.json()["session_id"]

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    second = client.post(
        "/api/ai/categorize", json={"session_id": session_id, "message": "E' Nikko"}
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert second.json()["place_name"] == "Nikko"


def test_categorize_matches_existing_location_case_insensitive(client, session, monkeypatch):
    hub = Location(name="Nikko", is_hub=False, parent_id=None)
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.add(hub)
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
            "place_name": "nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "high",
            "question": None,
        },
    )

    response = client.post("/api/ai/categorize", json={"message": "Tempio a Nikko"})
    assert response.json()["matched_location_id"] == hub.id


def test_categorize_with_unknown_session_id_returns_404(client):
    response = client.post(
        "/api/ai/categorize",
        json={"session_id": "does-not-exist", "message": "Ciao"},
    )
    assert response.status_code == 404


def test_categorize_forces_question_when_new_location_missing_coordinates(client, session, monkeypatch):
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

    response = client.post("/api/ai/categorize", json={"message": "Un vicolo di street food"})
    assert response.status_code == 200
    assert response.json()["question"] is not None
    assert "coordinate" in response.json()["question"].lower()

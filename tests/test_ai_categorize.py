import json

import anthropic
from sqlmodel import select

from app.ai import client as ai_client
from app.models import Category, Location, Reel
from app.routers.ai_categorize import _resolve_location_and_create_reel, _run_turn


def test_categorize_creates_session_and_returns_proposal(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    def fake_categorize(hub_names, categories, messages):
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
    def fake_categorize(hub_names, categories, messages):
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

    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: {
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
        lambda hub_names, categories, messages: {
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
        lambda hub_names, categories, messages: {
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


def test_categorize_returns_friendly_question_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert "riprova" in response.json()["question"].lower()


def test_categorize_returns_friendly_question_when_ai_call_raises_runtime_error(client, session, monkeypatch):
    # Regression: categorize() can raise RuntimeError (e.g. a pause_turn
    # search loop that never resolves) — this must fall back to the same
    # friendly question as anthropic.AnthropicError, not a raw 500.
    def boom(hub_names, categories, messages):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert "riprova" in response.json()["question"].lower()


def test_empty_place_name_does_not_spuriously_match_location(client, session, monkeypatch):
    # Regression: when AI call fails, place_name is "" (empty string).
    # Before fix: "" in any location name is always True, so it would
    # spuriously match the first location. After fix: returns None.
    location = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(location)
    session.commit()
    session.refresh(location)

    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert response.json()["matched_location_id"] is None


def test_assistant_history_sent_to_model_is_natural_language_not_json(session, monkeypatch):
    # Regression: the assistant's previous structured turn used to be replayed
    # to the model as a raw json.dumps(...) blob, which can anchor the model
    # into repeating the same (null) lat/lon turn after turn. It should be
    # sent as plain text instead.
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "?",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Che citta' e'?",
            "lat": None,
            "lon": None,
        },
    )
    ai_session, _, _ = _run_turn(session, None, "Un tempio in montagna")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Nikko",
            "near_hub": None,
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
            "lat": 36.7199,
            "lon": 139.6982,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "E' Nikko")

    assistant_messages = [m for m in captured["messages"] if m["role"] == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "Che citta' e'?"
    assert not assistant_messages[0]["content"].strip().startswith("{")


def test_assistant_proposal_history_is_summarized_not_raw_json(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
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
    ai_session, _, _ = _run_turn(session, None, "Ramen a Tokyo")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "conferma")

    assistant_text = [m for m in captured["messages"] if m["role"] == "assistant"][0]["content"]
    assert "Ichiran Ramen" in assistant_text
    assert not assistant_text.strip().startswith("{")


def test_safety_net_backfills_hub_coordinates_immediately_when_near_hub_is_known(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Shinjuku",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Street food area",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    ai_session, first_result, _ = _run_turn(session, None, "Cibo di strada a Shinjuku")
    assert first_result["question"] is None
    assert first_result["lat"] == 35.6762
    assert first_result["lon"] == 139.6503


def test_safety_net_falls_back_to_hub_coordinates_once_near_hub_becomes_known(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Shinjuku",
            "near_hub": None,
            "types": ["food"],
            "note": "Street food area",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    ai_session, first_result, _ = _run_turn(session, None, "Cibo di strada a Shinjuku")
    assert first_result["question"] is not None
    assert first_result["lat"] is None

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Shinjuku",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Street food area",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    ai_session2, second_result, matched = _run_turn(session, ai_session.id, "Shinjuku, Tokyo")
    assert second_result["question"] is None
    assert second_result["lat"] == 35.6762
    assert second_result["lon"] == 139.6503


def test_categorize_response_round_trips_candidates(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "Anime merchandise store",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    response = client.post(
        "/api/ai/categorize", json={"message": "The world's first dedicated Dragon Ball store"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["question"] is None
    assert data["candidates"] == ["Tokyo - Ikebukuro", "Osaka - Namba"]


def test_categorize_response_omits_candidates_by_default(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": None,
            "types": ["food"],
            "note": "",
            "confidence": "high",
            "question": None,
            "lat": 35.0,
            "lon": 135.0,
        },
    )

    response = client.post("/api/ai/categorize", json={"message": "Ramen"})
    assert response.json()["candidates"] is None


def test_safety_net_does_not_trigger_when_candidates_present(session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    _, result, _ = _run_turn(session, None, "Dragon Ball store")
    assert result["question"] is None
    assert result["candidates"] == ["Tokyo - Ikebukuro", "Osaka - Namba"]


def test_assistant_candidates_history_is_summarized_not_raw_json(session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )
    ai_session, _, _ = _run_turn(session, None, "Dragon Ball store")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "high",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "Tokyo - Ikebukuro")

    assistant_text = [m for m in captured["messages"] if m["role"] == "assistant"][0]["content"]
    assert "Tokyo - Ikebukuro" in assistant_text
    assert "Osaka - Namba" in assistant_text
    assert not assistant_text.strip().startswith("{")


def test_resolve_location_and_create_reel_uses_matched_location(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session,
        "https://instagram.com/reel/abc",
        "Tokyo / Kanto",
        "",
        ["food"],
        "Ramen chain",
        "",
        "",
        hub.id,
    )

    assert reel.location_id == hub.id
    assert session.exec(select(Location)).all() == [hub]


def test_resolve_location_and_create_reel_creates_new_satellite_under_hub(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="nature", label="Natura", icon="🌸", color="#7A8F5E"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session,
        "https://instagram.com/reel/nikko",
        "Nikko",
        "Tokyo / Kanto",
        ["nature"],
        "Shrine town",
        "36.7198",
        "139.6982",
        "",
    )

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert reel.location_id == satellite.id

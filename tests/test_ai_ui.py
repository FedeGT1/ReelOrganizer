import anthropic
from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiMessage, AiSession, Category, Location, Reel


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
    assert "Conferma e salva" not in response.text


def test_ui_ai_message_shows_confirm_button_when_proposal_is_complete(client, session, monkeypatch):
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
    assert "Conferma e salva" in response.text


def test_ui_ai_confirm_with_matched_location_creates_reel_on_existing_location(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "matched_location_id": hub.id,
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
    session.add(Category(key="nature", label="Natura", icon="🌸", color="#7A8F5E"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/nikko",
            "place_name": "Nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "lat": "36.7198",
            "lon": "139.6982",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert satellite.lat == 36.7198


def test_ui_ai_confirm_creates_new_hub_when_no_hub_matches(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200

    location = session.exec(select(Location).where(Location.name == "Sapporo Ramen Alley")).first()
    assert location is not None
    assert location.is_hub is True
    assert location.parent_id is None


def test_ui_ai_confirm_rejects_invalid_link(client, session):
    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "javascript:alert(1)",
            "place_name": "Somewhere",
            "near_hub": "",
            "types": [],
            "note": "",
            "lat": "1.0",
            "lon": "1.0",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_confirm_resets_panel_and_updates_reel_list(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "matched_location_id": hub.id,
        },
    )
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert "Conferma e salva" not in response.text
    assert 'hx-swap-oob="innerHTML:#reel-list"' in response.text
    assert "https://instagram.com/reel/abc" in response.text


def test_ui_ai_confirm_cleans_up_the_ai_session(client, session, monkeypatch):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
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
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200
    assert session.exec(select(AiSession).where(AiSession.id == ai_session_id)).first() is None
    assert session.exec(select(AiMessage).where(AiMessage.session_id == ai_session_id)).all() == []


def test_ui_ai_message_shows_friendly_error_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Qualcosa"},
    )
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_ai_message_with_unknown_session_id_resets_panel_with_notice(client, session):
    response = client.post(
        "/ui/ai/message",
        data={"session_id": "does-not-exist", "link": "https://instagram.com/reel/abc", "message": "Ciao"},
    )
    assert response.status_code == 200
    assert 'name="link"' in response.text
    assert "Sessione scaduta" in response.text

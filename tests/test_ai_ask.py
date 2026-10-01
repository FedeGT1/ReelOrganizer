from sqlmodel import select

from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
from app.models import AskMessage, AskSession, Category, Location, Reel, ReelType
from app.routers.ai_ask import _build_ask_chat_context, _run_ask_turn, _scoped_reel_context


def test_scoped_reel_context_filters_by_city_and_includes_satellites(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(satellite)
    session.add(other_hub)
    session.commit()
    session.refresh(satellite)
    session.refresh(other_hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen"))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=satellite.id, note="Shrine"))
    session.add(Reel(link="https://instagram.com/reel/3", location_id=other_hub.id, note="Takoyaki"))
    session.commit()

    entries, truncated = _scoped_reel_context(session, hub.id, None)

    assert truncated is False
    assert {e["place_name"] for e in entries} == {"Tokyo / Kanto", "Nikko"}


def test_scoped_reel_context_filters_by_category(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="nature", label="Natura", icon="🌸", color="#7A8F5E"))
    session.commit()
    session.refresh(hub)

    food_reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen")
    nature_reel = Reel(link="https://instagram.com/reel/2", location_id=hub.id, note="Park")
    session.add(food_reel)
    session.add(nature_reel)
    session.commit()
    session.refresh(food_reel)
    session.refresh(nature_reel)
    session.add(ReelType(reel_id=food_reel.id, type="food"))
    session.add(ReelType(reel_id=nature_reel.id, type="nature"))
    session.commit()

    entries, _ = _scoped_reel_context(session, hub.id, "food")

    assert len(entries) == 1
    assert entries[0]["note"] == "Ramen"
    assert entries[0]["categories"] == ["Cibo"]


def test_scoped_reel_context_with_no_filters_returns_all_reels(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=other_hub.id))
    session.commit()

    entries, truncated = _scoped_reel_context(session, None, None)

    assert len(entries) == 2
    assert truncated is False


def test_scoped_reel_context_truncates_beyond_max_and_flags_it(session, monkeypatch):
    import app.routers.ai_ask as ai_ask_module

    monkeypatch.setattr(ai_ask_module, "MAX_REELS_IN_CONTEXT", 2)
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    for i in range(3):
        session.add(Reel(link=f"https://instagram.com/reel/{i}", location_id=hub.id))
    session.commit()

    entries, truncated = _scoped_reel_context(session, hub.id, None)

    assert len(entries) == 2
    assert truncated is True


def test_run_ask_turn_creates_session_with_scope_and_calls_ai(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    captured = {}

    def fake_ask(reels, location_name, category_label, truncated, messages):
        captured["location_name"] = location_name
        return {"answer": "Ti consiglio di andare a Tokyo."}

    monkeypatch.setattr(ai_client, "ask", fake_ask)

    ask_session = _run_ask_turn(session, None, hub.id, None, "Cosa mi consigli?")

    assert ask_session.location_id == hub.id
    assert captured["location_name"] == "Tokyo / Kanto"
    messages = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].content == "Ti consiglio di andare a Tokyo."


def test_run_ask_turn_continuing_session_ignores_resubmitted_scope(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    ask_session = _run_ask_turn(session, None, hub.id, None, "Prima domanda")

    captured = {}

    def fake_ask(reels, location_name, category_label, truncated, messages):
        captured["location_name"] = location_name
        return {"answer": "seconda risposta"}

    monkeypatch.setattr(ai_client, "ask", fake_ask)
    # location_id passed here (other_hub.id) must be ignored in favor of the
    # session's own stored scope (hub.id), since the reel context must stay
    # consistent with what the first turn's answer was based on.
    _run_ask_turn(session, ask_session.id, other_hub.id, None, "Seconda domanda")

    assert captured["location_name"] == "Tokyo / Kanto"


def test_run_ask_turn_with_unknown_session_id_raises_404(session):
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        _run_ask_turn(session, "does-not-exist", None, None, "Ciao")
    assert exc_info.value.status_code == 404


def test_run_ask_turn_falls_back_to_friendly_answer_on_provider_error(session, monkeypatch):
    def boom(*a, **k):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "ask", boom)

    ask_session = _run_ask_turn(session, None, None, None, "Qualcosa")

    messages = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    assert "riprova" in messages[1].content.lower()


def test_build_ask_chat_context_with_no_session_has_empty_history(session):
    context = _build_ask_chat_context(session, None, None, None)
    assert context["history"] == []
    assert context["session_id"] == ""


def test_build_ask_chat_context_with_session_includes_history(session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta"})
    ask_session = _run_ask_turn(session, None, None, None, "domanda")

    context = _build_ask_chat_context(session, ask_session.id, None, None)

    assert context["session_id"] == ask_session.id
    assert [h["role"] for h in context["history"]] == ["user", "assistant"]
    assert context["history"][0]["text"] == "domanda"
    assert context["history"][1]["text"] == "risposta"


def test_ui_ask_panel_renders_empty_state(client):
    response = client.get("/ui/ask/panel")
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert 'name="location_id"' in response.text
    assert 'name="category_key"' in response.text


def test_ui_ask_message_first_turn_creates_session_and_shows_answer(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "Ti consiglio Ichiran Ramen."})

    response = client.post(
        "/ui/ask/message",
        data={"location_id": hub.id, "category_key": "", "message": "Dove mangio?"},
    )
    assert response.status_code == 200
    assert "Ti consiglio Ichiran Ramen." in response.text
    assert session.exec(select(AskSession)).first() is not None


def test_ui_ask_message_continues_existing_session(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "prima risposta"})
    first = client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"})
    assert "prima risposta" in first.text
    session_id = session.exec(select(AskSession)).first().id

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "seconda risposta"})
    second = client.post(
        "/ui/ask/message",
        data={"session_id": session_id, "location_id": "", "category_key": "", "message": "e poi?"},
    )
    assert second.status_code == 200
    assert "prima risposta" in second.text
    assert "seconda risposta" in second.text


def test_ui_ask_message_with_unknown_session_id_resets_panel_with_notice(client, session):
    response = client.post(
        "/ui/ask/message",
        data={"session_id": "does-not-exist", "location_id": "", "category_key": "", "message": "Ciao"},
    )
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert "Sessione scaduta" in response.text


def test_ui_ask_message_shows_friendly_error_when_ai_call_fails(client, session, monkeypatch):
    def boom(*a, **k):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "ask", boom)

    response = client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "Qualcosa"}
    )
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_ask_panel_lists_hubs_and_categories(client, session):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/ask/panel")
    assert "Tokyo / Kanto" in response.text
    assert "Cibo" in response.text
    assert "Tutte le citt" in response.text
    assert "Tutte le categorie" in response.text


def test_ui_ask_message_response_includes_filter_selects_for_next_turn(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})

    response = client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"}
    )
    assert 'name="location_id"' in response.text
    assert 'name="category_key"' in response.text

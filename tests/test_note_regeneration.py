from sqlmodel import select

from app.ai import client as ai_client
from app.models import Location, Reel
from app.routers.note_regeneration import _regen_source_message


def test_regen_source_message_prefers_caption_and_transcript():
    reel = Reel(link="x", location_id="loc", caption="Ramen a Tokyo", transcript="Il miglior ramen", note="vecchia nota")
    message = _regen_source_message(reel)
    assert "Didascalia: Ramen a Tokyo" in message
    assert "Trascrizione audio: Il miglior ramen" in message
    assert "vecchia nota" not in message


def test_regen_source_message_falls_back_to_current_note():
    reel = Reel(link="x", location_id="loc", caption=None, transcript=None, note="vecchia nota")
    message = _regen_source_message(reel)
    assert message == "Nota attuale: vecchia nota"


def test_regen_source_message_returns_none_when_nothing_available():
    reel = Reel(link="x", location_id="loc", caption=None, transcript=None, note=None)
    assert _regen_source_message(reel) is None


def _fake_categorize(note_value):
    def _inner(hub_names, categories, messages):
        return {
            "place_name": "Ichiran Ramen",
            "near_hub": None,
            "types": [],
            "note": note_value,
            "confidence": "high",
            "question": None,
            "lat": None,
            "lon": None,
        }

    return _inner


def test_ui_regenerate_reel_note_updates_note_from_caption_and_transcript(client, session, monkeypatch, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(
        link="https://instagram.com/reel/abc",
        location_id=hub.id,
        note="vecchia nota",
        caption="Ramen a Tokyo",
        transcript="Il miglior ramen della citta",
        user_id=test_user_id,
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)

    monkeypatch.setattr(ai_client, "categorize", _fake_categorize("Nota rigenerata e piu ricca"))

    response = client.put(f"/ui/reels/{reel.id}/regenerate-note")
    assert response.status_code == 200
    assert "Nota rigenerata e piu ricca" in response.text

    session.refresh(reel)
    assert reel.note == "Nota rigenerata e piu ricca"


def test_ui_regenerate_reel_note_falls_back_to_current_note_when_no_source(client, session, monkeypatch, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/abc", location_id=hub.id, note="vecchia nota", user_id=test_user_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    monkeypatch.setattr(ai_client, "categorize", _fake_categorize("Nota rigenerata dalla vecchia nota"))

    response = client.put(f"/ui/reels/{reel.id}/regenerate-note")
    assert response.status_code == 200

    session.refresh(reel)
    assert reel.note == "Nota rigenerata dalla vecchia nota"


def test_ui_regenerate_reel_note_keeps_old_note_on_ai_failure(client, session, monkeypatch, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(
        link="https://instagram.com/reel/abc",
        location_id=hub.id,
        note="vecchia nota",
        caption="Ramen a Tokyo",
        user_id=test_user_id,
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)

    def failing_categorize(hub_names, categories, messages):
        return {
            "place_name": "",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None,
            "lon": None,
        }

    monkeypatch.setattr(ai_client, "categorize", failing_categorize)

    response = client.put(f"/ui/reels/{reel.id}/regenerate-note")
    assert response.status_code == 200
    assert "Non sono riuscito a rigenerare" in response.text

    session.refresh(reel)
    assert reel.note == "vecchia nota"


def test_ui_regenerate_reel_note_unknown_id_returns_404(client, session):
    response = client.put("/ui/reels/does-not-exist/regenerate-note")
    assert response.status_code == 404


def test_regenerate_note_for_another_users_reel_returns_404(client, session):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    other_reel = Reel(
        link="x", location_id=other_hub.id, caption="test", user_id="other-user"
    )
    session.add(other_reel)
    session.commit()
    session.refresh(other_reel)

    response = client.put(f"/ui/reels/{other_reel.id}/regenerate-note")

    assert response.status_code == 404


def test_ui_regenerate_all_notes_updates_only_eligible_reels(client, session, monkeypatch, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    with_source = Reel(
        link="https://instagram.com/reel/a",
        location_id=hub.id,
        note="vecchia nota a",
        caption="Caption A",
        user_id=test_user_id,
    )
    with_only_note = Reel(
        link="https://instagram.com/reel/b", location_id=hub.id, note="vecchia nota b", user_id=test_user_id
    )
    nothing_at_all = Reel(link="https://instagram.com/reel/c", location_id=hub.id, note=None, user_id=test_user_id)
    session.add(with_source)
    session.add(with_only_note)
    session.add(nothing_at_all)
    session.commit()
    session.refresh(with_source)
    session.refresh(with_only_note)
    session.refresh(nothing_at_all)

    monkeypatch.setattr(ai_client, "categorize", _fake_categorize("Nota rigenerata"))

    response = client.post("/ui/reels/regenerate-notes")
    assert response.status_code == 200
    assert "2 nota/e aggiornata/e" in response.text
    assert "1 saltata/e" in response.text

    session.refresh(with_source)
    session.refresh(with_only_note)
    session.refresh(nothing_at_all)
    assert with_source.note == "Nota rigenerata"
    assert with_only_note.note == "Nota rigenerata"
    assert nothing_at_all.note is None

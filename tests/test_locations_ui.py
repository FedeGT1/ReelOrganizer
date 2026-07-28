from app.models import Location


def test_ui_locations_list_renders_existing_locations(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    response = client.get("/ui/locations")
    assert response.status_code == 200
    assert "Tokyo / Kanto" in response.text
    assert "<form" in response.text


def test_ui_locations_list_shows_satellite_parent_name(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Kamakura", is_hub=False, parent_id=hub.id, lat=35.3, lon=139.5)
    session.add(satellite)
    session.commit()

    response = client.get("/ui/locations")
    assert response.status_code == 200
    assert "Kamakura" in response.text
    assert "Tokyo / Kanto" in response.text


def test_ui_locations_create_hub_and_rerenders_list(client):
    response = client.post(
        "/ui/locations",
        data={"name": "New Hub", "is_hub": "true", "lat": "10.0", "lon": "20.0"},
    )
    assert response.status_code == 200
    assert "New Hub" in response.text


def test_ui_locations_create_satellite_without_parent_shows_inline_error(client):
    response = client.post(
        "/ui/locations",
        data={"name": "Orphan", "is_hub": "false", "lat": "10.0", "lon": "20.0"},
    )
    assert response.status_code == 200
    assert "richiede" in response.text.lower()


def test_ui_locations_edit_form_renders_prefilled_row(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.get(f"/ui/locations/{hub.id}/edit")
    assert response.status_code == 200
    assert 'value="Tokyo / Kanto"' in response.text


def test_ui_locations_edit_form_unknown_id_returns_404(client):
    response = client.get("/ui/locations/does-not-exist/edit")
    assert response.status_code == 404


def test_ui_locations_update_and_rerenders_list(client, session):
    hub = Location(name="Old Name", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        f"/ui/locations/{hub.id}",
        data={"name": "New Name", "is_hub": "true", "lat": "36.0", "lon": "136.0"},
    )
    assert response.status_code == 200
    assert "New Name" in response.text


def test_ui_locations_delete_removes_it_and_rerenders_list(client, session):
    hub = Location(name="Doomed", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.delete(f"/ui/locations/{hub.id}")
    assert response.status_code == 200
    assert "Doomed" not in response.text


def test_ui_locations_delete_with_children_shows_inline_error(client, session):
    hub = Location(name="Parent Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Child Satellite", is_hub=False, parent_id=hub.id, lat=35.1, lon=135.1)
    session.add(satellite)
    session.commit()

    response = client.delete(f"/ui/locations/{hub.id}")
    assert response.status_code == 200
    assert "Parent Hub" in response.text
    assert "riassegn" in response.text.lower()

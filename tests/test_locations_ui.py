from app.models import Location, Reel


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


def test_ui_locations_list_groups_satellites_under_their_hub_and_indents_them(client, session):
    hub_b = Location(name="Zeta Hub", is_hub=True, lat=30.0, lon=130.0)
    hub_a = Location(name="Alpha Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub_b)
    session.add(hub_a)
    session.commit()
    session.refresh(hub_b)
    session.refresh(hub_a)

    satellite_of_b = Location(name="Zeta Satellite", is_hub=False, parent_id=hub_b.id, lat=30.1, lon=130.1)
    satellite_of_a = Location(name="Alpha Satellite", is_hub=False, parent_id=hub_a.id, lat=35.1, lon=135.1)
    session.add(satellite_of_b)
    session.add(satellite_of_a)
    session.commit()

    response = client.get("/ui/locations")
    assert response.status_code == 200

    text = response.text
    positions = {
        name: text.index(name)
        for name in ["Alpha Hub", "Alpha Satellite", "Zeta Hub", "Zeta Satellite"]
    }
    assert positions["Alpha Hub"] < positions["Alpha Satellite"] < positions["Zeta Hub"]
    assert positions["Zeta Hub"] < positions["Zeta Satellite"]
    assert 'class="satellite-row"' in text


def test_ui_locations_delete_with_reels_shows_inline_error(client, session):
    hub = Location(name="Hub With Reels", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id))
    session.commit()

    response = client.delete(f"/ui/locations/{hub.id}")
    assert response.status_code == 200
    assert "Hub With Reels" in response.text
    assert "reel" in response.text.lower()


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

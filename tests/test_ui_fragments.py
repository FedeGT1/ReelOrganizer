import json
import re

from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def _map_data(response_text: str) -> list[dict]:
    match = re.search(
        r'<script type="application/json" id="map-data">(.*?)</script>',
        response_text,
        re.DOTALL,
    )
    assert match, "map-data JSON blob not found in response"
    return json.loads(match.group(1))


def test_ui_map_renders_leaflet_container_and_location_data(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/tokyo", location_id=hub.id))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert 'id="leaflet-map"' in response.text

    locations = _map_data(response.text)
    assert len(locations) == 1
    assert locations[0]["name"] == "Tokyo / Kanto"
    assert locations[0]["lat"] == 35.6762
    assert locations[0]["lon"] == 139.6503


def test_ui_map_includes_type_filter_chips(client, session):
    from app.models import Category

    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'data-type="food"' in response.text
    assert "window.toggleType('food')" in response.text
    assert "window.clearTypes()" in response.text


def test_ui_map_marks_multiple_active_chips(client, session):
    from app.models import Category

    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="shopping", label="Shopping", icon="🛍️", color="#35496B"))
    session.commit()

    response = client.get("/ui/map?type=food&type=shopping")
    assert response.status_code == 200

    import re

    food_chip = re.search(r'<a[^>]*data-type="food"[^>]*>', response.text).group(0)
    shopping_chip = re.search(r'<a[^>]*data-type="shopping"[^>]*>', response.text).group(0)
    assert "active" in food_chip
    assert "active" in shopping_chip


def test_ui_map_type_filter_excludes_hub_without_matching_reel(client, session):
    hub_with_food = Location(name="Has Food", is_hub=True, lat=35.0, lon=135.0)
    hub_without_food = Location(name="No Food", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub_with_food)
    session.add(hub_without_food)
    session.commit()
    session.refresh(hub_with_food)
    session.refresh(hub_without_food)

    reel = Reel(link="https://instagram.com/reel/f", location_id=hub_with_food.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get("/ui/map?type=food")
    assert response.status_code == 200

    locations = {loc["id"]: loc for loc in _map_data(response.text)}
    assert locations[hub_with_food.id]["dimmed"] is False
    assert hub_without_food.id not in locations


def test_ui_map_okinawa_renders_at_its_real_coordinates(client, session):
    okinawa = Location(name="Okinawa", is_hub=True, lat=26.2124, lon=127.6809)
    session.add(okinawa)
    session.commit()
    session.refresh(okinawa)
    session.add(Reel(link="https://instagram.com/reel/okinawa", location_id=okinawa.id))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200

    locations = _map_data(response.text)
    assert len(locations) == 1
    assert locations[0]["name"] == "Okinawa"
    assert locations[0]["lat"] == 26.2124
    assert locations[0]["lon"] == 127.6809


def test_ui_map_removes_empty_hub_by_default(client, session):
    empty_hub = Location(name="Empty Hub", is_hub=True, lat=35.0, lon=135.0)
    filled_hub = Location(name="Filled Hub", is_hub=True, lat=36.0, lon=136.0)
    session.add(empty_hub)
    session.add(filled_hub)
    session.commit()
    session.refresh(filled_hub)
    session.add(Reel(link="https://instagram.com/reel/d", location_id=filled_hub.id))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200

    ids = {loc["id"] for loc in _map_data(response.text)}
    assert filled_hub.id in ids
    assert empty_hub.id not in ids


def test_ui_reels_get_renders_list_without_form(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot"))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Nice spot" in response.text
    assert "<form" not in response.text


def test_ui_reels_add_form_renders_locations_and_categories(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/reels/add-form")
    assert response.status_code == 200
    assert "<form" in response.text
    assert "Tokyo / Kanto" in response.text
    assert "Cibo" in response.text


def test_ui_reels_post_resets_form_and_refreshes_list_and_map(client, session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "https://instagram.com/reel/new", "location_id": hub.id, "note": "New one", "types": ["food"]},
    )
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "reel-saved"
    assert '<div hx-swap-oob="innerHTML:#reel-list">' in response.text
    assert "New one" in response.text
    assert '<div hx-swap-oob="innerHTML:#map-container">' in response.text
    assert 'id="leaflet-map"' in response.text


def test_ui_reels_post_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_reels_delete_returns_updated_fragment(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/gone", location_id=hub.id, note="Bye")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.delete(f"/ui/reels/{reel.id}")
    assert response.status_code == 200
    assert "Bye" not in response.text


def test_ui_reels_get_filters_by_location_id(client, session):
    hub_a = Location(name="Hub A", is_hub=True, lat=35.0, lon=135.0)
    hub_b = Location(name="Hub B", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub_a)
    session.add(hub_b)
    session.commit()
    session.refresh(hub_a)
    session.refresh(hub_b)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id, note="A spot"))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub_b.id, note="B spot"))
    session.commit()

    response = client.get(f"/ui/reels?location_id={hub_a.id}")
    assert response.status_code == 200
    assert "A spot" in response.text
    assert "B spot" not in response.text
    assert "Hub A" in response.text
    assert "Mostra tutti" in response.text


def test_ui_reels_get_by_hub_location_id_includes_satellite_reels(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(name="Kamakura", is_hub=False, parent_id=hub.id)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)

    session.add(Reel(link="https://instagram.com/reel/hub", location_id=hub.id, note="Hub spot"))
    session.add(
        Reel(link="https://instagram.com/reel/satellite", location_id=satellite.id, note="Satellite spot")
    )
    session.commit()

    response = client.get(f"/ui/reels?location_id={hub.id}")
    assert response.status_code == 200
    assert "Hub spot" in response.text
    assert "Satellite spot" in response.text


def test_ui_reels_get_without_filter_shows_no_banner(client):
    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Mostra tutti" not in response.text


def test_ui_reels_mostra_tutti_banner_uses_clear_location_filter(client, session):
    hub_a = Location(name="Hub A", is_hub=True)
    session.add(hub_a)
    session.commit()
    session.refresh(hub_a)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id))
    session.commit()

    response = client.get(f"/ui/reels?location_id={hub_a.id}")
    assert response.status_code == 200
    assert "window.clearLocationFilter()" in response.text


def test_ui_reels_edit_form_renders_prefilled_data(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get(f"/ui/reels/{reel.id}/edit-form")
    assert response.status_code == 200
    assert 'value="https://instagram.com/reel/x"' in response.text
    assert 'value="Nice spot"' in response.text
    assert f'value="{hub.id}" selected' in response.text
    assert 'value="food" checked' in response.text


def test_ui_reels_edit_form_missing_reel_returns_404(client):
    response = client.get("/ui/reels/does-not-exist/edit-form")
    assert response.status_code == 404


def test_ui_reels_put_resets_form_and_refreshes_list_and_map(client, session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    other_hub = Location(name="Other Hub", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)
    reel = Reel(link="https://instagram.com/reel/old", location_id=hub.id, note="Old note")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.put(
        f"/ui/reels/{reel.id}",
        data={"link": "https://instagram.com/reel/new", "location_id": other_hub.id, "note": "New note"},
    )
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "reel-saved"
    assert '<div hx-swap-oob="innerHTML:#reel-list">' in response.text
    assert "New note" in response.text
    assert '<div hx-swap-oob="innerHTML:#map-container">' in response.text
    assert 'id="leaflet-map"' in response.text


def test_ui_reels_put_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/keep", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.put(
        f"/ui/reels/{reel.id}",
        data={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400


def test_ui_reels_list_includes_edit_button(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert f"/ui/reels/{reel.id}/edit-form" in response.text


def test_ui_reels_list_google_maps_link_uses_place_name_by_default(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "https://www.google.com/maps/search/?api=1&query=Tokyo%20/%20Kanto" in response.text


def test_ui_reels_list_google_maps_link_uses_coordinates_when_confidence_is_low(client, session):
    hub = Location(
        name="Mystery Alley", is_hub=True, lat=35.0067, lon=135.7727, geocode_confidence="low"
    )
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "https://www.google.com/maps/search/?api=1&query=35.0067%2C135.7727" in response.text


def test_ui_reels_list_omits_google_maps_link_when_low_confidence_and_no_coordinates(client, session):
    hub = Location(name="Hub", is_hub=True, geocode_confidence="low")
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "google.com/maps" not in response.text


def test_ui_reels_get_filters_by_type(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#35496B"))
    session.commit()
    session.refresh(hub)

    reel_food = Reel(link="https://instagram.com/reel/food", location_id=hub.id, note="Ramen spot")
    reel_culture = Reel(link="https://instagram.com/reel/culture", location_id=hub.id, note="Shrine visit")
    session.add(reel_food)
    session.add(reel_culture)
    session.commit()
    session.refresh(reel_food)
    session.refresh(reel_culture)
    session.add(ReelType(reel_id=reel_food.id, type="food"))
    session.add(ReelType(reel_id=reel_culture.id, type="culture"))
    session.commit()

    response = client.get("/ui/reels?type=food")
    assert response.status_code == 200
    assert "Ramen spot" in response.text
    assert "Shrine visit" not in response.text

import re

from sqlmodel import select

from app.models import Location, Reel, ReelType


def test_ui_map_renders_svg_with_stations(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "<svg" in response.text
    assert "Tokyo / Kanto" in response.text


def test_ui_map_includes_type_filter_chips(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'hx-get="/ui/map?type=food"' in response.text


def test_ui_map_dims_stations_without_the_selected_type(client, session):
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

    with_food_class = re.search(
        rf'class="([^"]*)" data-location-id="{hub_with_food.id}"', response.text
    ).group(1)
    without_food_class = re.search(
        rf'class="([^"]*)" data-location-id="{hub_without_food.id}"', response.text
    ).group(1)

    assert "dimmed" not in with_food_class
    assert "dimmed" in without_food_class


def test_ui_map_renders_coastline_and_sea(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert '<path d="M ' in response.text
    assert 'class="sea"' in response.text


def test_ui_map_renders_okinawa_inset_box(client, session):
    okinawa = Location(name="Okinawa", is_hub=True, lat=26.2124, lon=127.6809, map_inset=True)
    session.add(okinawa)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert 'class="inset-box"' in response.text
    assert "Okinawa" in response.text


def test_ui_map_hide_empty_removes_empty_hub_from_svg(client, session):
    empty_hub = Location(name="Empty Hub", is_hub=True, lat=35.0, lon=135.0)
    filled_hub = Location(name="Filled Hub", is_hub=True, lat=36.0, lon=136.0)
    session.add(empty_hub)
    session.add(filled_hub)
    session.commit()
    session.refresh(filled_hub)
    session.add(Reel(link="https://instagram.com/reel/d", location_id=filled_hub.id))
    session.commit()

    response = client.get("/ui/map?hide_empty=1")
    assert response.status_code == 200
    assert "Filled Hub" in response.text
    assert "Empty Hub" not in response.text


def test_ui_map_toggle_chip_label_reflects_state(client):
    response = client.get("/ui/map")
    assert "Nascondi vuoti" in response.text

    response = client.get("/ui/map?hide_empty=1")
    assert "Mostra tutti" in response.text


def test_ui_reels_get_renders_list_and_form(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot"))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Nice spot" in response.text
    assert "<form" in response.text


def test_ui_reels_post_creates_and_returns_fragment(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "https://instagram.com/reel/new", "location_id": hub.id, "note": "New one", "types": ["food"]},
    )
    assert response.status_code == 200
    assert "New one" in response.text


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

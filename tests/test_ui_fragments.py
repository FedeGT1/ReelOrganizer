import re

from app.models import Location, Reel, ReelType


def test_ui_map_renders_svg_with_stations(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
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
    hub_with_food = Location(name="Has Food", is_hub=True, x=10.0, y=10.0)
    hub_without_food = Location(name="No Food", is_hub=True, x=20.0, y=20.0)
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

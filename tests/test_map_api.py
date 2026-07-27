from app.models import Location, Reel, ReelType
from app.routers.map import compute_map, visible_location_ids


def test_map_returns_lat_lon_for_hub_and_satellite(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(
        name="Nikko", is_hub=False, parent_id=hub.id, lat=36.7199, lon=139.6982
    )
    session.add(satellite)
    session.commit()

    response = client.get("/api/map")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    hub_entry = next(d for d in data if d["is_hub"])
    sat_entry = next(d for d in data if not d["is_hub"])
    assert hub_entry["lat"] == 35.6762
    assert hub_entry["lon"] == 139.6503
    assert sat_entry["parent_id"] == hub.id
    assert "x" not in hub_entry and "y" not in hub_entry
    assert "map_inset" not in hub_entry


def test_visible_location_ids_hides_hub_with_no_reels_and_no_filled_children(session):
    empty_hub = Location(name="Empty", is_hub=True, lat=35.0, lon=135.0)
    filled_hub = Location(name="Filled", is_hub=True, lat=36.0, lon=136.0)
    session.add(empty_hub)
    session.add(filled_hub)
    session.commit()
    session.refresh(filled_hub)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=filled_hub.id))
    session.commit()

    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, None)

    assert filled_hub.id in visible_ids
    assert empty_hub.id not in visible_ids
    assert anchors == set()


def test_visible_location_ids_keeps_empty_hub_as_anchor_for_filled_satellite(session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id, lat=35.1, lon=135.1)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)
    session.add(Reel(link="https://instagram.com/reel/b", location_id=satellite.id))
    session.commit()

    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, None)

    assert hub.id in visible_ids
    assert satellite.id in visible_ids
    assert hub.id in anchors


def test_visible_location_ids_uses_type_specific_emptiness_when_type_active(session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/c", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    locations = compute_map(session)
    visible_ids, _ = visible_location_ids(session, locations, "culture")

    assert hub.id not in visible_ids

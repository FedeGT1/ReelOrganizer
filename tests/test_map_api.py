from app.models import Location


def test_map_computes_satellite_positions(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
    session.add(satellite)
    session.commit()

    response = client.get("/api/map")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    hub_entry = next(d for d in data if d["is_hub"])
    sat_entry = next(d for d in data if not d["is_hub"])
    assert hub_entry["x"] == 200.0
    assert sat_entry["parent_id"] == hub.id
    assert sat_entry["x"] != hub_entry["x"] or sat_entry["y"] != hub_entry["y"]

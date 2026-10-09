from sqlmodel import select

from app.models import Location, Reel, ReelType


def test_delete_location_with_reels_returns_409(client, session, test_user_id):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub With Reels", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub_id, user_id=test_user_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.delete(f"/api/locations/{hub_id}")
    assert response.status_code == 409

    names = {loc["name"] for loc in client.get("/api/locations").json()}
    assert "Hub With Reels" in names
    assert session.exec(select(Reel).where(Reel.location_id == hub_id)).all() != []
    assert session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all() != []


def test_delete_missing_location_returns_404(client):
    response = client.delete("/api/locations/does-not-exist")
    assert response.status_code == 404


def test_list_locations_includes_reel_counts(client, session, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id, user_id=test_user_id))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=hub.id, user_id=test_user_id))
    session.commit()

    response = client.get("/api/locations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Tokyo / Kanto"
    assert data[0]["reel_count"] == 2


def test_list_locations_empty(client):
    response = client.get("/api/locations")
    assert response.status_code == 200
    assert response.json() == []


def test_create_hub_location(client):
    response = client.post(
        "/api/locations",
        json={"name": "Test Hub", "is_hub": True, "lat": 10.0, "lon": 20.0},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Hub"
    assert data["id"]


def test_create_location_without_lat_lon_returns_422(client):
    response = client.post("/api/locations", json={"name": "No Coords", "is_hub": True})
    assert response.status_code == 422


def test_create_satellite_location(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Parent Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.post(
        "/api/locations",
        json={"name": "Satellite Town", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == hub_id


def test_create_satellite_location_without_parent_id_returns_400(client):
    response = client.post(
        "/api/locations",
        json={"name": "Orphan", "is_hub": False, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 400


def test_delete_location_with_children_returns_409(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub With Kids", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    satellite_resp = client.post(
        "/api/locations",
        json={"name": "Satellite Kid", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )
    assert satellite_resp.status_code == 201

    response = client.delete(f"/api/locations/{hub_id}")
    assert response.status_code == 409

    names = {loc["name"] for loc in client.get("/api/locations").json()}
    assert "Hub With Kids" in names
    assert "Satellite Kid" in names


def test_update_location_changes_fields(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Old Name", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "New Name", "is_hub": True, "lat": 36.0, "lon": 136.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["lat"] == 36.0
    assert data["lon"] == 136.0


def test_update_missing_location_returns_404(client):
    response = client.put(
        "/api/locations/does-not-exist",
        json={"name": "X", "is_hub": True, "lat": 0.0, "lon": 0.0},
    )
    assert response.status_code == 404


def test_update_satellite_without_parent_id_returns_400(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Hub", "is_hub": False, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 400


def test_update_hub_with_children_to_satellite_returns_409(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Parent Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]
    other_hub_resp = client.post(
        "/api/locations", json={"name": "Other Hub", "is_hub": True, "lat": 30.0, "lon": 130.0}
    )
    other_hub_id = other_hub_resp.json()["id"]
    client.post(
        "/api/locations",
        json={"name": "Satellite Kid", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Parent Hub", "is_hub": False, "parent_id": other_hub_id, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 409


def test_update_hub_ignores_submitted_parent_id(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub A", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]
    other_hub_resp = client.post(
        "/api/locations", json={"name": "Hub B", "is_hub": True, "lat": 30.0, "lon": 130.0}
    )
    other_hub_id = other_hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Hub A", "is_hub": True, "parent_id": other_hub_id, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] is None


def test_merge_locations_reassigns_reels_and_deletes_drop(client, session, test_user_id):
    keep = Location(name="Shibuya", is_hub=False, lat=35.6590, lon=139.7005, user_id=test_user_id)
    drop = Location(name="Shibuya Crossing", is_hub=False, lat=35.6591, lon=139.7006, user_id=test_user_id)
    session.add(keep)
    session.add(drop)
    session.commit()
    session.refresh(keep)
    session.refresh(drop)

    reel = Reel(link="https://instagram.com/reel/x", location_id=drop.id, note="nota", user_id=test_user_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.post(f"/api/locations/{keep.id}/merge/{drop.id}")
    assert response.status_code == 204

    session.refresh(reel)
    assert reel.location_id == keep.id
    assert session.get(Location, drop.id) is None
    kept = session.get(Location, keep.id)
    assert kept.name == "Shibuya"
    assert kept.lat == 35.6590


def test_merge_locations_blocks_when_drop_has_children(client, session, test_user_id):
    hub = Location(name="Hub A", is_hub=True, user_id=test_user_id)
    other_hub = Location(name="Hub B", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id, user_id=test_user_id)
    session.add(satellite)
    session.commit()

    response = client.post(f"/api/locations/{other_hub.id}/merge/{hub.id}")
    assert response.status_code == 409
    assert session.get(Location, hub.id) is not None


def test_merge_locations_returns_404_for_missing_ids(client, session, test_user_id):
    hub = Location(name="Hub", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(f"/api/locations/{hub.id}/merge/does-not-exist")
    assert response.status_code == 404


def test_list_locations_only_returns_current_users_locations(client, session):
    from app.models import Location

    session.add(Location(name="Someone Else's Hub", is_hub=True, user_id="other-user"))
    session.commit()

    response = client.get("/api/locations")

    assert response.status_code == 200
    assert "Someone Else's Hub" not in {loc["name"] for loc in response.json()}


def test_create_location_with_another_users_parent_id_returns_404(client, session):
    from app.models import Location

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)

    response = client.post(
        "/api/locations",
        json={"name": "Satellite", "is_hub": False, "parent_id": other_hub.id, "lat": 1.0, "lon": 2.0},
    )

    assert response.status_code == 404

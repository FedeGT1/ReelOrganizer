from app.models import Location, Reel, ReelType


def test_delete_location_cascades_reels(client, session):
    hub_resp = client.post("/api/locations", json={"name": "Doomed Hub", "is_hub": True})
    hub_id = hub_resp.json()["id"]

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.delete(f"/api/locations/{hub_id}")
    assert response.status_code == 204

    assert client.get("/api/locations").json() == []


def test_delete_missing_location_returns_404(client):
    response = client.delete("/api/locations/does-not-exist")
    assert response.status_code == 404


def test_list_locations_includes_reel_counts(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=hub.id))
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
        json={"name": "Test Hub", "is_hub": True, "x": 10.0, "y": 20.0},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Hub"
    assert data["id"]


def test_create_satellite_location(client):
    hub_resp = client.post("/api/locations", json={"name": "Parent Hub", "is_hub": True})
    hub_id = hub_resp.json()["id"]

    response = client.post(
        "/api/locations",
        json={"name": "Satellite Town", "is_hub": False, "parent_id": hub_id},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == hub_id

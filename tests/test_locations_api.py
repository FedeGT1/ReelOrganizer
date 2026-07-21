from app.models import Location, Reel


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

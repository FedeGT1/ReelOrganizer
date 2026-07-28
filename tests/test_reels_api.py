from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def test_list_reels_with_types(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get("/api/reels")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["types"] == ["food"]


def test_filter_reels_by_location_id(client, session):
    hub_a = Location(name="Hub A", is_hub=True)
    hub_b = Location(name="Hub B", is_hub=True)
    session.add(hub_a)
    session.add(hub_b)
    session.commit()
    session.refresh(hub_a)
    session.refresh(hub_b)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub_b.id))
    session.commit()

    response = client.get(f"/api/reels?location_id={hub_a.id}")
    data = response.json()
    assert len(data) == 1
    assert data[0]["location_id"] == hub_a.id


def test_filter_reels_by_hub_location_id_includes_satellites(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(name="Kamakura", is_hub=False, parent_id=hub.id)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)

    session.add(Reel(link="https://instagram.com/reel/hub", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/satellite", location_id=satellite.id))
    session.commit()

    response = client.get(f"/api/reels?location_id={hub.id}")
    data = response.json()
    assert {r["location_id"] for r in data} == {hub.id, satellite.id}


def test_filter_reels_by_type(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel_food = Reel(link="https://instagram.com/reel/food", location_id=hub.id)
    reel_culture = Reel(link="https://instagram.com/reel/culture", location_id=hub.id)
    session.add(reel_food)
    session.add(reel_culture)
    session.commit()
    session.refresh(reel_food)
    session.refresh(reel_culture)
    session.add(ReelType(reel_id=reel_food.id, type="food"))
    session.add(ReelType(reel_id=reel_culture.id, type="culture"))
    session.commit()

    response = client.get("/api/reels?type=food")
    data = response.json()
    assert len(data) == 1
    assert data[0]["link"] == "https://instagram.com/reel/food"


def test_create_reel_filters_invalid_types(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/api/reels",
        json={
            "link": "https://instagram.com/reel/new",
            "location_id": hub.id,
            "note": "Great ramen",
            "types": ["food", "not-a-real-type"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["types"] == ["food"]
    assert data["note"] == "Great ramen"


def test_delete_reel(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    create_resp = client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/gone", "location_id": hub.id, "types": ["food"]},
    )
    reel_id = create_resp.json()["id"]

    response = client.delete(f"/api/reels/{reel_id}")
    assert response.status_code == 204
    assert client.get("/api/reels").json() == []
    assert session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all() == []


def test_delete_missing_reel_returns_404(client):
    response = client.delete("/api/reels/does-not-exist")
    assert response.status_code == 404


def test_create_reel_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/api/reels",
        json={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_update_reel_changes_fields(client, session):
    hub = Location(name="Hub", is_hub=True)
    other_hub = Location(name="Other Hub", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#8FA8B2"))
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    create_resp = client.post(
        "/api/reels",
        json={
            "link": "https://instagram.com/reel/old",
            "location_id": hub.id,
            "note": "Old note",
            "types": ["food"],
        },
    )
    reel_id = create_resp.json()["id"]

    response = client.put(
        f"/api/reels/{reel_id}",
        json={
            "link": "https://instagram.com/reel/new",
            "location_id": other_hub.id,
            "note": "New note",
            "types": ["culture"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["link"] == "https://instagram.com/reel/new"
    assert data["location_id"] == other_hub.id
    assert data["note"] == "New note"
    assert data["types"] == ["culture"]

    # The old "food" ReelType row must actually be gone, not just superseded.
    remaining_types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    assert [t.type for t in remaining_types] == ["culture"]


def test_update_missing_reel_returns_404(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.put(
        "/api/reels/does-not-exist",
        json={"link": "https://instagram.com/reel/x", "location_id": hub.id},
    )
    assert response.status_code == 404


def test_update_reel_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    create_resp = client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/keep", "location_id": hub.id, "types": ["food"]},
    )
    reel_id = create_resp.json()["id"]

    response = client.put(
        f"/api/reels/{reel_id}",
        json={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert client.get("/api/reels").json()[0]["link"] == "https://instagram.com/reel/keep"

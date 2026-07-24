from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def test_list_categories_empty(client):
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []


def test_list_categories_returns_seeded_rows(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/api/categories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["key"] == "food"
    assert data[0]["label"] == "Cibo"


def test_create_category_generates_slug_key(client):
    response = client.post(
        "/api/categories",
        json={"label": "Vita notturna", "icon": "🍿", "color": "#7A4B8A"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"] == "vita-notturna"
    assert data["label"] == "Vita notturna"
    assert data["icon"] == "🍿"
    assert data["color"] == "#7A4B8A"


def test_create_category_normalizes_accented_characters(client):
    response = client.post(
        "/api/categories",
        json={"label": "Città storica", "icon": "🏯", "color": "#35496B"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "citta-storica"


def test_create_category_rejects_duplicate_slug(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.post(
        "/api/categories",
        json={"label": "Food", "icon": "🍔", "color": "#000000"},
    )
    assert response.status_code == 409


def test_create_category_rejects_unslugifiable_label(client):
    response = client.post(
        "/api/categories",
        json={"label": "🎉🎉🎉", "icon": "🎉", "color": "#000000"},
    )
    assert response.status_code == 400


def test_update_category_changes_label_icon_color_not_key(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.put(
        "/api/categories/food",
        json={"label": "Cibo di strada", "icon": "🌭", "color": "#111111"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "food"
    assert data["label"] == "Cibo di strada"
    assert data["icon"] == "🌭"
    assert data["color"] == "#111111"


def test_update_unknown_category_returns_404(client):
    response = client.put(
        "/api/categories/does-not-exist",
        json={"label": "X", "icon": "🍜", "color": "#000000"},
    )
    assert response.status_code == 404


def test_delete_category_removes_only_matching_reel_types(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#35496B"))
    session.commit()

    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.add(ReelType(reel_id=reel.id, type="culture"))
    session.commit()

    response = client.delete("/api/categories/food")
    assert response.status_code == 204

    assert session.get(Category, "food") is None
    assert session.get(Category, "culture") is not None
    remaining_types = {
        t.type for t in session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    }
    assert remaining_types == {"culture"}
    assert session.get(Reel, reel.id) is not None


def test_delete_unknown_category_returns_404(client):
    response = client.delete("/api/categories/does-not-exist")
    assert response.status_code == 404


def test_create_category_rejects_invalid_color_format(client):
    response = client.post(
        "/api/categories",
        json={"label": "Test", "icon": "🎉", "color": "not-a-color"},
    )
    assert response.status_code == 422

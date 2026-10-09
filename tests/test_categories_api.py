from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def test_list_categories_empty(client):
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []


def test_list_categories_returns_seeded_rows(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
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
        json={"label": "Vita notturna", "icon": "🍿"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"] == "vita-notturna"
    assert data["label"] == "Vita notturna"
    assert data["icon"] == "🍿"


def test_create_category_normalizes_accented_characters(client):
    response = client.post(
        "/api/categories",
        json={"label": "Città storica", "icon": "🏯"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "citta-storica"


def test_create_category_rejects_duplicate_slug(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.post(
        "/api/categories",
        json={"label": "Food", "icon": "🍔"},
    )
    assert response.status_code == 409


def test_create_category_rejects_unslugifiable_label(client):
    response = client.post(
        "/api/categories",
        json={"label": "🎉🎉🎉", "icon": "🎉"},
    )
    assert response.status_code == 400


def test_update_category_changes_label_icon_not_key(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.put(
        "/api/categories/food",
        json={"label": "Cibo di strada", "icon": "🌭"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "food"
    assert data["label"] == "Cibo di strada"
    assert data["icon"] == "🌭"


def test_update_unknown_category_returns_404(client):
    response = client.put(
        "/api/categories/does-not-exist",
        json={"label": "X", "icon": "🍜"},
    )
    assert response.status_code == 404


def test_delete_category_removes_only_matching_reel_types(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", user_id=test_user_id))
    session.commit()

    hub = Location(name="Hub", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id, user_id=test_user_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.add(ReelType(reel_id=reel.id, type="culture"))
    session.commit()

    response = client.delete("/api/categories/food")
    assert response.status_code == 204

    assert session.get(Category, (test_user_id, "food")) is None
    assert session.get(Category, (test_user_id, "culture")) is not None
    remaining_types = {
        t.type for t in session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    }
    assert remaining_types == {"culture"}
    assert session.get(Reel, reel.id) is not None


def test_delete_unknown_category_returns_404(client):
    response = client.delete("/api/categories/does-not-exist")
    assert response.status_code == 404


def test_list_categories_only_returns_current_users_categories(client, session):
    from app.models import Category

    session.add(Category(user_id="other-user", key="other", label="Other", icon="❓"))
    session.commit()

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert "other" not in {c["key"] for c in response.json()}


def test_delete_category_does_not_delete_another_users_reeltype_with_same_key(client, session):
    from app.models import Category, Location, Reel, ReelType

    client.post("/api/categories", json={"label": "Cibo", "icon": "🍜"})

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    other_reel = Reel(link="https://instagram.com/reel/x", location_id=other_hub.id, user_id="other-user")
    session.add(other_reel)
    session.commit()
    session.refresh(other_reel)
    session.add(Category(user_id="other-user", key="cibo", label="Food", icon="🍔"))
    session.add(ReelType(reel_id=other_reel.id, type="cibo"))
    session.commit()

    response = client.delete("/api/categories/cibo")
    assert response.status_code == 204

    remaining = session.exec(select(ReelType).where(ReelType.reel_id == other_reel.id)).all()
    assert len(remaining) == 1

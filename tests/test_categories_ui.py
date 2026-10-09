from app.models import Category


def test_ui_categories_list_renders_existing_categories(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.get("/ui/categories")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert "🍜" in response.text
    assert "<form" in response.text


def test_ui_categories_create_and_rerenders_list(client, session, test_user_id):
    response = client.post(
        "/ui/categories",
        data={"label": "Vita notturna", "icon": "🍿"},
    )
    assert response.status_code == 200
    assert "Vita notturna" in response.text
    assert session.get(Category, (test_user_id, "vita-notturna")) is not None


def test_ui_categories_edit_form_renders_prefilled_row(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.get("/ui/categories/food/edit")
    assert response.status_code == 200
    assert 'value="Cibo"' in response.text
    assert 'value="🍜"' in response.text


def test_ui_categories_edit_form_unknown_key_returns_404(client):
    response = client.get("/ui/categories/does-not-exist/edit")
    assert response.status_code == 404


def test_ui_categories_update_and_rerenders_list(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.post(
        "/ui/categories/food",
        data={"label": "Cibo di strada", "icon": "🌭"},
    )
    assert response.status_code == 200
    assert "Cibo di strada" in response.text
    assert session.get(Category, (test_user_id, "food")).label == "Cibo di strada"


def test_ui_categories_delete_removes_it_and_rerenders_list(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()

    response = client.delete("/ui/categories/food")
    assert response.status_code == 200
    assert "Cibo" not in response.text
    assert session.get(Category, (test_user_id, "food")) is None

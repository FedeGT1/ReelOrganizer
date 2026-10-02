def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Japan Reel Organizer" in response.text
    assert 'id="map-container"' in response.text


def test_index_page_loads_custom_fonts(client):
    response = client.get("/")
    assert "Shippori+Mincho" in response.text
    assert "Zen+Kaku+Gothic+New" in response.text


def test_index_page_renders_add_reel_dialog(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="add-reel-dialog"' in response.text
    assert 'id="open-add-reel"' in response.text
    assert 'data-tab="ai"' in response.text
    assert 'data-tab="manual"' in response.text
    assert 'id="ai-chat-panel"' in response.text
    assert 'id="reel-add-form-panel"' in response.text


def test_index_page_loads_reel_dialog_script(client):
    response = client.get("/")
    assert '/static/js/reel-dialog.js' in response.text


def test_index_page_renders_search_input(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="reel-search-input"' in response.text
    assert "window.handleSearchInput(this.value)" in response.text

def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Japan Reel Organizer" in response.text
    assert 'id="map-container"' in response.text


def test_index_page_loads_custom_fonts(client):
    response = client.get("/")
    assert "Shippori+Mincho" in response.text
    assert "Zen+Kaku+Gothic+New" in response.text

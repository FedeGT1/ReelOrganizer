def test_locations_page_renders(client):
    response = client.get("/locations")
    assert response.status_code == 200
    assert 'id="location-list"' in response.text


def test_nav_includes_locations_link(client):
    response = client.get("/")
    assert 'href="/locations"' in response.text
    assert "Gestisci città" in response.text

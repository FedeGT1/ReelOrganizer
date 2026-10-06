def test_locations_page_renders(client):
    response = client.get("/locations")
    assert response.status_code == 200
    assert 'id="location-list"' in response.text


def test_nav_includes_strumenti_link(client):
    response = client.get("/")
    assert 'href="/strumenti"' in response.text
    assert "Strumenti" in response.text

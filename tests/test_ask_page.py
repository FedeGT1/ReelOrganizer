def test_ask_page_renders(client):
    response = client.get("/ask")
    assert response.status_code == 200
    assert 'id="ask-chat-panel"' in response.text


def test_nav_includes_ask_link(client):
    response = client.get("/")
    assert 'href="/ask"' in response.text

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(name="anon_client")
def anon_client_fixture():
    from app.main import app

    return TestClient(app, base_url="https://testserver")


def test_get_login_returns_form(anon_client):
    response = anon_client.get("/login")
    assert response.status_code == 200
    assert "form" in response.text.lower()


def test_post_login_wrong_credentials_shows_error(anon_client):
    response = anon_client.post("/login", data={"username": "testuser", "password": "wrong"})
    assert response.status_code == 401
    assert "non valide" in response.text.lower()


def test_post_login_correct_credentials_redirects_and_sets_cookie(anon_client):
    response = anon_client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "session=" in response.headers.get("set-cookie", "")


def test_logout_redirects_to_login():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

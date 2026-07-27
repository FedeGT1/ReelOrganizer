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


def test_logout_redirects_to_login(client):
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_unauthenticated_request_to_page_redirects_to_login(anon_client):
    response = anon_client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login"


def test_unauthenticated_request_to_api_returns_401(anon_client):
    response = anon_client.get("/api/reels")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_health_and_static_remain_public(anon_client):
    response = anon_client.get("/health")
    assert response.status_code == 200

    response = anon_client.get("/static/js/map.js")
    assert response.status_code == 200


def test_htmx_request_gets_hx_redirect_header_instead_of_full_redirect(anon_client):
    response = anon_client.get("/ui/reels", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/login"


def test_login_unlocks_access_to_protected_routes(anon_client):
    response = anon_client.get("/api/reels")
    assert response.status_code == 401

    anon_client.post("/login", data={"username": "testuser", "password": "testpass"})

    response = anon_client.get("/api/reels")
    assert response.status_code == 200


def test_authenticated_client_can_reach_protected_routes(client):
    response = client.get("/api/reels")
    assert response.status_code == 200


def test_lockout_after_five_failed_attempts(anon_client):
    for _ in range(5):
        response = anon_client.post("/login", data={"username": "testuser", "password": "wrong"})
        assert response.status_code == 401

    response = anon_client.post("/login", data={"username": "testuser", "password": "testpass"})
    assert response.status_code == 429

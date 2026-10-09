def test_locations_created_by_one_user_are_invisible_to_another(client, second_user_client):
    client.post(
        "/api/locations",
        json={"name": "User A's Secret Hub", "is_hub": True, "lat": 1.0, "lon": 2.0},
    )

    response = second_user_client.get("/api/locations")

    assert "User A's Secret Hub" not in {loc["name"] for loc in response.json()}


def test_reels_created_by_one_user_are_invisible_to_another(client, second_user_client):
    hub_response = client.post(
        "/api/locations", json={"name": "A's Hub", "is_hub": True, "lat": 1.0, "lon": 2.0}
    )
    hub_id = hub_response.json()["id"]
    client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/secret", "location_id": hub_id, "note": "segreto di A"},
    )

    response = second_user_client.get("/api/reels")

    assert "segreto di A" not in {r.get("note") for r in response.json()}


def test_categories_created_by_one_user_are_invisible_to_another_even_with_same_label(
    client, second_user_client
):
    client.post("/api/categories", json={"label": "Cibo", "icon": "🍜"})
    second_user_client.post("/api/categories", json={"label": "Cibo", "icon": "🍔"})

    a_categories = {c["icon"] for c in client.get("/api/categories").json() if c["key"] == "cibo"}
    b_categories = {c["icon"] for c in second_user_client.get("/api/categories").json() if c["key"] == "cibo"}

    assert a_categories == {"🍜"}
    assert b_categories == {"🍔"}


def test_fetching_another_users_reel_by_id_returns_404_not_403(client, second_user_client):
    hub_response = client.post(
        "/api/locations", json={"name": "A's Hub", "is_hub": True, "lat": 1.0, "lon": 2.0}
    )
    hub_id = hub_response.json()["id"]
    reel_response = client.post(
        "/api/reels", json={"link": "https://instagram.com/reel/x", "location_id": hub_id}
    )
    reel_id = reel_response.json()["id"]

    response = second_user_client.put(
        f"/api/reels/{reel_id}",
        json={"link": "https://instagram.com/reel/y", "location_id": hub_id, "types": []},
    )

    assert response.status_code == 404


def test_map_export_and_audit_views_do_not_leak_across_users(client, second_user_client):
    client.post("/api/locations", json={"name": "A's Secret Place", "is_hub": True, "lat": 1.0, "lon": 2.0})

    map_response = second_user_client.get("/api/map")
    export_response = second_user_client.get("/api/export/markdown")
    audit_response = second_user_client.get("/ui/audit/scan")

    assert "A's Secret Place" not in {loc["name"] for loc in map_response.json()}
    assert "A's Secret Place" not in export_response.text
    assert "A's Secret Place" not in audit_response.text


def test_each_new_user_gets_their_own_seeded_hubs_and_categories(
    client, second_user_client, session, test_user_id
):
    # The shared `client`/testuser fixture (tests/conftest.py) is deliberately
    # left unseeded so the rest of the suite can start from an empty slate
    # (see Task 5's note). `second_user_client` mirrors a real admin-created
    # account and is seeded via seed_user_if_empty in its own fixture. To
    # exercise "a real account, created the same way scripts/create_user.py
    # creates them" for *both* users in this one test without reseeding the
    # shared fixture for every other test file, seed testuser here directly.
    from app.seed import seed_user_if_empty

    seed_user_if_empty(session, test_user_id)

    a_locations = client.get("/api/locations").json()
    b_locations = second_user_client.get("/api/locations").json()

    assert len(a_locations) == 20
    assert len(b_locations) == 20
    # Different rows (different ids), not the same 20 shared between both users.
    assert {loc["id"] for loc in a_locations}.isdisjoint({loc["id"] for loc in b_locations})

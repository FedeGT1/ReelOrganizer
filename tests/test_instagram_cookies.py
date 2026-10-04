def test_ui_instagram_cookies_status_shows_absent_when_no_file(client, monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(tmp_path / "missing.txt"))

    response = client.get("/ui/instagram-cookies")

    assert response.status_code == 200
    assert "Nessun cookie caricato" in response.text


def test_ui_instagram_cookies_upload_saves_file_and_shows_present(client, monkeypatch, tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_path))

    response = client.post(
        "/ui/instagram-cookies",
        files={"cookies_file": ("cookies.txt", b"# Netscape HTTP Cookie File\n", "text/plain")},
    )

    assert response.status_code == 200
    assert cookies_path.read_bytes() == b"# Netscape HTTP Cookie File\n"
    assert "ultimo aggiornamento" in response.text.lower()


def test_ui_instagram_cookies_upload_rejects_empty_file(client, monkeypatch, tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("existing content")
    monkeypatch.setenv("INSTAGRAM_COOKIES_PATH", str(cookies_path))

    response = client.post(
        "/ui/instagram-cookies",
        files={"cookies_file": ("cookies.txt", b"", "text/plain")},
    )

    assert response.status_code == 200
    assert "vuoto" in response.text.lower()
    assert cookies_path.read_text() == "existing content"


def test_instagram_cookies_page_renders(client):
    response = client.get("/instagram-cookies")

    assert response.status_code == 200
    assert 'hx-get="/ui/instagram-cookies"' in response.text

from app.ingest import instagram, transcribe


def test_ui_ai_panel_shows_import_button_before_any_session(client):
    response = client.get("/ui/ai/panel")

    assert response.status_code == 200
    assert 'id="ai-import-link"' in response.text
    assert 'hx-post="/ui/ai/import"' in response.text


def test_ui_ai_import_prefills_caption_and_transcript(client, session, monkeypatch):
    def fake_fetch(url, download_dir):
        video_path = download_dir / "reel.mp4"
        video_path.write_bytes(b"fake")
        return instagram.FetchResult(caption="Ramen a Tokyo", video_path=video_path)

    monkeypatch.setattr(instagram, "fetch", fake_fetch)
    monkeypatch.setattr(transcribe, "transcribe", lambda video_path: "Questo e' il miglior ramen di Tokyo")

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/abc"})

    assert response.status_code == 200
    assert "Ramen a Tokyo" in response.text
    assert "miglior ramen di Tokyo" in response.text
    assert 'value="https://instagram.com/reel/abc"' in response.text


def test_ui_ai_import_rejects_non_instagram_link(client, session):
    response = client.post("/ui/ai/import", data={"link": "https://tiktok.com/reel/abc"})

    assert response.status_code == 200
    assert "reel Instagram" in response.text


def test_ui_ai_import_falls_back_to_manual_entry_on_fetch_error(client, session, monkeypatch):
    def failing_fetch(url, download_dir):
        raise instagram.InstagramFetchError("private reel")

    monkeypatch.setattr(instagram, "fetch", failing_fetch)

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/private"})

    assert response.status_code == 200
    assert "Non sono riuscito a importare" in response.text
    assert 'name="message" placeholder="Descrizione o didascalia del reel" required></textarea>' in response.text


def test_ui_ai_import_proceeds_with_caption_only_when_transcription_fails(client, session, monkeypatch):
    def fake_fetch(url, download_dir):
        video_path = download_dir / "reel.mp4"
        video_path.write_bytes(b"fake")
        return instagram.FetchResult(caption="Tempio a Kyoto", video_path=video_path)

    def failing_transcribe(video_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(instagram, "fetch", fake_fetch)
    monkeypatch.setattr(transcribe, "transcribe", failing_transcribe)

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/abc"})

    assert response.status_code == 200
    assert "Tempio a Kyoto" in response.text
    assert "trascrizione non disponibile" in response.text

from app.models import Category, Location, Reel, ReelType


def test_export_markdown_groups_by_hub_and_location(client, session):
    tokyo = Location(name="Tokyo", is_hub=True)
    kyoto = Location(name="Kyoto", is_hub=True)
    session.add(tokyo)
    session.add(kyoto)
    session.commit()
    session.refresh(tokyo)
    session.refresh(kyoto)

    senso_ji = Location(name="Senso-ji Temple", is_hub=False, parent_id=tokyo.id)
    fushimi = Location(name="Fushimi Inari", is_hub=False, parent_id=kyoto.id)
    session.add(senso_ji)
    session.add(fushimi)
    session.commit()
    session.refresh(senso_ji)
    session.refresh(fushimi)

    session.add(Category(key="temple", label="Tempio", icon="⛩️"))
    session.commit()

    reel1 = Reel(link="https://instagram.com/reel/1", location_id=senso_ji.id, note="bellissimo al tramonto")
    reel2 = Reel(link="https://instagram.com/reel/2", location_id=fushimi.id, note="torii rossi")
    session.add(reel1)
    session.add(reel2)
    session.commit()
    session.refresh(reel1)
    session.add(ReelType(reel_id=reel1.id, type="temple"))
    session.commit()

    response = client.get("/api/export/markdown")
    assert response.status_code == 200
    body = response.text

    assert body.index("## Kyoto") < body.index("## Tokyo")
    assert "### Fushimi Inari" in body
    assert "### Senso-ji Temple" in body
    assert "- **Tempio** — bellissimo al tramonto" in body
    assert "- torii rossi" in body
    assert "# Itinerario" not in body


def test_export_markdown_bullet_omits_missing_note_or_categories(client, session):
    hub = Location(name="Tokyo", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

    reel_note_only = Reel(link="https://instagram.com/reel/a", location_id=hub.id, note="ottimo ramen")
    reel_category_only = Reel(link="https://instagram.com/reel/b", location_id=hub.id)
    session.add(reel_note_only)
    session.add(reel_category_only)
    session.commit()
    session.refresh(reel_category_only)
    session.add(ReelType(reel_id=reel_category_only.id, type="food"))
    session.commit()

    body = client.get("/api/export/markdown").text

    assert "- ottimo ramen" in body
    assert "- **Cibo**" in body
    assert "- **Cibo** —" not in body
    assert "ottimo ramen —" not in body


def test_export_markdown_skips_hubs_and_locations_without_reels(client, session):
    empty_hub = Location(name="Osaka", is_hub=True)
    hub_with_reel = Location(name="Tokyo", is_hub=True)
    session.add(empty_hub)
    session.add(hub_with_reel)
    session.commit()
    session.refresh(hub_with_reel)

    empty_satellite = Location(name="Shibuya", is_hub=False, parent_id=hub_with_reel.id)
    session.add(empty_satellite)
    session.commit()

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub_with_reel.id, note="nota"))
    session.commit()

    body = client.get("/api/export/markdown").text

    assert "Osaka" not in body
    assert "Shibuya" not in body
    assert "## Tokyo" in body


def test_export_markdown_filters_by_hub_id(client, session):
    tokyo = Location(name="Tokyo", is_hub=True)
    kyoto = Location(name="Kyoto", is_hub=True)
    session.add(tokyo)
    session.add(kyoto)
    session.commit()
    session.refresh(tokyo)
    session.refresh(kyoto)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=tokyo.id, note="tokyo nota"))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=kyoto.id, note="kyoto nota"))
    session.commit()

    response = client.get(f"/api/export/markdown?hub_id={tokyo.id}")
    body = response.text

    assert "## Tokyo" in body
    assert "## Kyoto" not in body


def test_export_markdown_unknown_hub_id_returns_404(client):
    response = client.get("/api/export/markdown?hub_id=does-not-exist")
    assert response.status_code == 404


def test_export_markdown_sets_filename_for_full_export(client, session):
    hub = Location(name="Tokyo", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="nota"))
    session.commit()

    response = client.get("/api/export/markdown")
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="export.md"' in response.headers["content-disposition"]


def test_export_markdown_sets_filename_for_hub_export(client, session):
    hub = Location(name="Tokyo", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="nota"))
    session.commit()

    response = client.get(f"/api/export/markdown?hub_id={hub.id}")
    assert 'filename="export-tokyo.md"' in response.headers["content-disposition"]


def test_export_markdown_with_no_reels_returns_empty_body(client):
    response = client.get("/api/export/markdown")
    assert response.status_code == 200
    assert response.text.strip() == ""


def test_export_page_renders_shell(client):
    response = client.get("/export")
    assert response.status_code == 200


def test_export_panel_lists_hubs(client, session):
    hub = Location(name="Tokyo", is_hub=True)
    session.add(hub)
    session.commit()

    response = client.get("/ui/export")
    assert response.status_code == 200
    assert "Tokyo" in response.text

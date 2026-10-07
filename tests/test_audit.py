from app.models import Location, Reel


def test_audit_scan_flags_certain_duplicate(client, session):
    loc_a = Location(name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77)
    loc_b = Location(name="Surugaya Akihabara (駿河屋秋葉原)", is_hub=False, lat=35.7001, lon=139.7701)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()
    session.refresh(loc_a)
    session.refresh(loc_b)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=loc_a.id, note="Negozio di hobby"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Surugaya" in response.text
    assert "Nessun duplicato quasi certo trovato." not in response.text
    # The actual reel card (home-list layout) is rendered for the pair.
    assert "Negozio di hobby" in response.text
    assert "btn-edit" in response.text
    assert "btn-delete" in response.text


def test_audit_scan_excludes_same_spot_different_business_sharing_only_a_district_word(client, session):
    # Same exact coordinates, but the only shared word is the district
    # name ("Shibuya") -- real data showed this pattern is normal city
    # density, not a duplicate signal, even at 0m apart.
    loc_a = Location(name="Starbucks Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    loc_b = Location(name="Pokémon Center Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "audit-pair" not in response.text


def test_audit_scan_excludes_unrelated_names_merely_within_the_wide_candidate_radius(client, session):
    # Two real, distinct, unrelated places that just happen to be ~1km
    # apart in the same city -- common in any dense tourist area, and not
    # a meaningful duplicate signal on its own.
    loc_a = Location(name="Yasaka Koshindo", is_hub=False, lat=35.0036, lon=135.7788)
    loc_b = Location(name="Kawadoko sul fiume Kamogawa", is_hub=False, lat=35.0100, lon=135.7700)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "audit-pair" not in response.text


def test_audit_scan_still_flags_a_related_name_beyond_the_tight_proximity_range(client, session):
    loc_a = Location(name="Ichiran Ramen Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    loc_b = Location(name="Ichiran Ramen Shibuya Ten", is_hub=False, lat=35.6680, lon=139.7110)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun caso da verificare." not in response.text
    assert "Ichiran Ramen Shibuya" in response.text


def test_audit_scan_excludes_tight_proximity_with_unrelated_names(client, session):
    loc_a = Location(name="M's Pop Life Adult Department Store", is_hub=False, lat=35.698, lon=139.771)
    loc_b = Location(name="BOOKOFF Akihabara Eki-mae", is_hub=False, lat=35.698, lon=139.771)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "audit-pair" not in response.text


def test_audit_scan_shows_empty_state_when_no_anomalies(client, session):
    session.add(Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun duplicato quasi certo trovato." in response.text
    assert "Nessun caso da verificare." in response.text
    assert "Nessuna coordinata imprecisa trovata." in response.text
    assert "Nessuna location con confidenza bassa." in response.text
    assert "Nessun reel da dividere trovato." in response.text


def test_audit_scan_does_not_list_the_same_pair_twice(client, session):
    loc_a = Location(name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)
    loc_b = Location(name="nishiki market", is_hub=False, lat=35.0051, lon=135.7651)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.text.count('class="audit-pair"') == 1


def test_audit_scan_does_not_duplicate_pair_across_sections_for_directional_match(client, session):
    # "Tokyo" (hub) auto-matches "Tokyo Bay Area" (hub) via the
    # short-name-contained-in-hub-label rule (tier 1), but the other hub's
    # own scan only finds "Tokyo" as a distance-based candidate (the
    # containment check only fires one direction) -- without fully
    # processing every `auto` match before any `candidate` match, this
    # pair would show up in both the certain and the review section.
    hub_a = Location(name="Tokyo Bay Area", is_hub=True, lat=35.6762, lon=139.6503)
    hub_b = Location(name="Tokyo", is_hub=True, lat=35.685, lon=139.655)
    session.add(hub_a)
    session.add(hub_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert response.text.count('class="audit-pair"') == 1


def test_audit_scan_never_flags_a_hub_against_its_own_satellite(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    satellite = Location(
        name="Mochimen UDON x MAGURO SUSHI", is_hub=False, parent_id=hub.id,
        lat=35.6762, lon=139.6503,
    )
    session.add(hub)
    session.add(satellite)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "audit-pair" not in response.text


def test_audit_scan_ignores_distance_between_satellites_that_inherited_the_same_hub_coordinates(client, session):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    tower = Location(name="Kyoto Tower", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681)
    kiyomizu = Location(name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.add(tower)
    session.add(kiyomizu)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "audit-pair" not in response.text


def test_audit_scan_still_flags_text_duplicates_that_share_inherited_hub_coordinates(client, session):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    loc_a = Location(name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681)
    loc_b = Location(name="kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert response.text.count('class="audit-pair"') == 1
    assert "Nessun duplicato quasi certo trovato." not in response.text


def test_audit_scan_flags_satellite_with_inherited_hub_coordinates(client, session):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    satellite = Location(
        name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681,
    )
    session.add(hub)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=satellite.id, note="Tempio famoso"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna coordinata imprecisa trovata." not in response.text
    assert "Kiyomizu-dera" in response.text
    assert "coordinate ereditate da Kyoto / Kansai" in response.text
    assert "Tempio famoso" in response.text


def test_audit_scan_does_not_flag_a_satellite_with_its_own_coordinates(client, session):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    satellite = Location(name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=34.9949, lon=135.7850)
    session.add(hub)
    session.add(satellite)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna coordinata imprecisa trovata." in response.text


def test_audit_scan_flags_low_confidence_location(client, session):
    loc = Location(
        name="Hama-Sushi (filiale non specificata)", is_hub=False, lat=35.0, lon=135.0,
        geocode_confidence="low",
    )
    session.add(loc)
    session.commit()
    session.refresh(loc)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=loc.id, note="Sushi a nastro"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna location con confidenza bassa." not in response.text
    assert "Hama-Sushi" in response.text
    assert "Sushi a nastro" in response.text


def test_audit_scan_does_not_flag_high_confidence_location(client, session):
    loc = Location(name="Kiyomizu-dera", is_hub=False, lat=35.0, lon=135.0, geocode_confidence="high")
    session.add(loc)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna location con confidenza bassa." in response.text


def test_audit_scan_flags_reel_that_may_need_splitting(client, session):
    # Real-world shape: two reels sharing the exact same link and the
    # exact same (too-generic) location, but describing two different
    # specific places in their notes -- a sign the location should be
    # split, not that anything should be merged.
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    session.add(kamakura)
    session.commit()
    session.refresh(kamakura)

    link = "https://www.instagram.com/reel/same-link/"
    session.add(Reel(link=link, location_id=kamakura.id, note="Grande statua del Buddha a Kotoku-in."))
    session.add(Reel(link=link, location_id=kamakura.id, note="Tempio famoso per i giardini e la vista."))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun reel da dividere trovato." not in response.text
    assert "Kamakura" in response.text
    assert "Grande statua del Buddha a Kotoku-in." in response.text
    assert "Tempio famoso per i giardini e la vista." in response.text


def test_audit_scan_does_not_flag_a_single_reel_per_link_as_a_split_candidate(client, session):
    loc = Location(name="Kiyomizu-dera", is_hub=False, lat=35.0, lon=135.0)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=loc.id, note="Tempio"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun reel da dividere trovato." in response.text


def test_audit_scan_does_not_flag_multi_place_reels_on_different_locations_as_split_candidates(client, session):
    # The normal multi-place import: one link, several DIFFERENT
    # locations -- this is not a split candidate, it's already split.
    loc_a = Location(name="Kiyomizu-dera", is_hub=False, lat=35.0, lon=135.0)
    loc_b = Location(name="Kinkaku-ji", is_hub=False, lat=35.03, lon=135.73)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()
    session.refresh(loc_a)
    session.refresh(loc_b)

    link = "https://www.instagram.com/reel/multi-place/"
    session.add(Reel(link=link, location_id=loc_a.id, note="Tempio A"))
    session.add(Reel(link=link, location_id=loc_b.id, note="Tempio B"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun reel da dividere trovato." in response.text


def test_ui_audit_merge_removes_pair_and_reassigns_reel(client, session):
    keep = Location(name="Shibuya Crossing", is_hub=False, lat=35.6590, lon=139.7005)
    drop = Location(name="Shibuya Crossing ", is_hub=False, lat=35.6591, lon=139.7006)
    session.add(keep)
    session.add(drop)
    session.commit()
    session.refresh(keep)
    session.refresh(drop)

    reel = Reel(link="https://instagram.com/reel/x", location_id=drop.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.post(f"/ui/audit/merge/{keep.id}/{drop.id}")
    assert response.status_code == 200
    assert "Nessun duplicato quasi certo trovato." in response.text

    session.refresh(reel)
    assert reel.location_id == keep.id
    assert session.get(Location, drop.id) is None


def test_ui_audit_merge_renders_error_when_drop_has_children(client, session):
    hub = Location(name="Hub A", is_hub=True, lat=35.0, lon=135.0)
    other_hub = Location(name="Hub B", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id, lat=35.001, lon=135.001)
    session.add(satellite)
    session.commit()

    response = client.post(f"/ui/audit/merge/{other_hub.id}/{hub.id}")
    assert response.status_code == 200
    assert "Impossibile unire" in response.text
    assert session.get(Location, hub.id) is not None


def test_strumenti_page_lists_tool_links(client):
    response = client.get("/strumenti")
    assert response.status_code == 200
    assert 'href="/categories"' in response.text
    assert 'href="/locations"' in response.text
    assert 'href="/export"' in response.text
    assert 'href="/instagram-cookies"' in response.text
    assert 'href="/strumenti/audit"' in response.text


def test_audit_page_renders(client):
    response = client.get("/strumenti/audit")
    assert response.status_code == 200
    assert 'hx-get="/ui/audit/scan"' in response.text
    assert 'id="add-reel-dialog"' in response.text

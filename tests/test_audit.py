import json

from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
from app.location_matching import NEW_HUB_SENTINEL
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
    # The "Chiedi all'AI" button shows a loading indicator and disables
    # itself while the request is in flight, so a slow AI call doesn't
    # look like nothing happened.
    assert 'hx-indicator="next .htmx-indicator"' in response.text
    assert 'hx-disabled-elt="this"' in response.text
    assert 'class="htmx-indicator"' in response.text
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


def test_audit_scan_ignores_distance_between_unrelated_locations_both_at_zero_coordinates(client, session):
    # Two different broken satellites that both happen to sit at the same
    # sentinel (0, 0) value must not look like they're "right next to
    # each other" -- that distance is meaningless, same reasoning as
    # hub-inherited coordinates.
    loc_a = Location(name="Posto Rotto A", is_hub=False, lat=0.0, lon=0.0)
    loc_b = Location(name="Posto Rotto B", is_hub=False, lat=0.0, lon=0.0)
    session.add(loc_a)
    session.add(loc_b)
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


def test_audit_scan_flags_satellite_with_zero_coordinates(client, session):
    # (0, 0) -- "null island" -- is never a real place in Japan; it's a
    # classic sentinel/default value from a bug or a bad manual edit.
    satellite = Location(name="Posto Rotto", is_hub=False, lat=0.0, lon=0.0)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=satellite.id, note="Nota"))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna coordinata imprecisa trovata." not in response.text
    assert "Posto Rotto" in response.text
    assert "0,0" in response.text or "0.0" in response.text


def test_audit_scan_flags_hub_with_zero_coordinates(client, session):
    # A hub at (0, 0) is just as broken as a satellite -- the existing
    # check only looked at satellites with a parent, which would have
    # missed this.
    hub = Location(name="Hub Rotto", is_hub=True, lat=0.0, lon=0.0)
    session.add(hub)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessuna coordinata imprecisa trovata." not in response.text
    assert "Hub Rotto" in response.text


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


def test_ui_audit_ai_geocode_shows_proposal_for_imprecise_location(client, session, monkeypatch):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    satellite = Location(name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=satellite.id, note="Tempio famoso"))
    session.commit()

    def fake_categorize(hub_names, categories, messages):
        assert "Kiyomizu-dera" in messages[0]["content"]
        return {
            "place_name": "Kiyomizu-dera", "near_hub": "Kyoto / Kansai", "types": [],
            "note": "", "confidence": "high", "question": None,
            "lat": 34.9949, "lon": 135.7850,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    response = client.post(f"/ui/audit/ai/geocode/{satellite.id}")
    assert response.status_code == 200
    assert "34.9949" in response.text
    assert "135.785" in response.text


def test_ui_audit_ai_geocode_handles_provider_error_gracefully(client, session, monkeypatch):
    loc = Location(name="Hama-Sushi (filiale non specificata)", is_hub=False, lat=35.0, lon=135.0, geocode_confidence="low")
    session.add(loc)
    session.commit()
    session.refresh(loc)

    def boom(hub_names, categories, messages):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post(f"/ui/audit/ai/geocode/{loc.id}")
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_audit_ai_geocode_returns_404_for_missing_location(client):
    response = client.post("/ui/audit/ai/geocode/does-not-exist")
    assert response.status_code == 404


def test_ui_audit_ai_geocode_apply_updates_location_coordinates(client, session):
    hub = Location(name="Kyoto / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    satellite = Location(
        name="Kiyomizu-dera", is_hub=False, parent_id=hub.id, lat=35.0116, lon=135.7681,
        geocode_confidence="low",
    )
    session.add(hub)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)

    response = client.post(
        f"/ui/audit/ai/geocode/apply/{satellite.id}",
        data={"lat": "34.9949", "lon": "135.7850", "confidence": "high"},
    )
    assert response.status_code == 200

    session.refresh(satellite)
    assert satellite.lat == 34.9949
    assert satellite.lon == 135.7850
    assert satellite.geocode_confidence == "high"


def test_ui_audit_ai_geocode_apply_returns_404_for_missing_location(client):
    response = client.post(
        "/ui/audit/ai/geocode/apply/does-not-exist", data={"lat": "1.0", "lon": "1.0"}
    )
    assert response.status_code == 404


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


def test_ui_audit_ai_compare_shows_different_verdict_in_the_matching_pair(client, session, monkeypatch):
    loc_a = Location(name="MODE OFF Hachioji Owada", is_hub=False, lat=35.0, lon=135.0)
    loc_b = Location(name="HARD-OFF Hachioji Owada", is_hub=False, lat=35.0001, lon=135.0001)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()
    session.refresh(loc_a)
    session.refresh(loc_b)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=loc_a.id, note="Vestiti usati"))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=loc_b.id, note="Elettronica usata"))
    session.commit()

    captured = {}

    def fake_compare(a_name, a_notes, b_name, b_notes):
        captured["args"] = (a_name, a_notes, b_name, b_notes)
        return {"same_place": False, "reasoning": "Negozi diversi dello stesso gruppo OFF."}

    monkeypatch.setattr(ai_client, "compare_places", fake_compare)

    response = client.post(f"/ui/audit/ai/compare/{loc_a.id}/{loc_b.id}")
    assert response.status_code == 200
    assert "Negozi diversi dello stesso gruppo OFF." in response.text
    assert captured["args"][0] == "MODE OFF Hachioji Owada"
    assert captured["args"][1] == ["Vestiti usati"]
    assert captured["args"][2] == "HARD-OFF Hachioji Owada"
    assert captured["args"][3] == ["Elettronica usata"]


def test_ui_audit_ai_compare_shows_same_place_verdict(client, session, monkeypatch):
    loc_a = Location(name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77)
    loc_b = Location(name="Surugaya Akihabara (駿河屋秋葉原)", is_hub=False, lat=35.7001, lon=139.7701)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    monkeypatch.setattr(
        ai_client, "compare_places",
        lambda a_name, a_notes, b_name, b_notes: {"same_place": True, "reasoning": "Stesso negozio, nome scritto diversamente."},
    )

    response = client.post(f"/ui/audit/ai/compare/{loc_a.id}/{loc_b.id}")
    assert response.status_code == 200
    assert "Stesso negozio, nome scritto diversamente." in response.text


def test_ui_audit_ai_compare_handles_provider_error_gracefully(client, session, monkeypatch):
    loc_a = Location(name="Posto A", is_hub=False, lat=35.0, lon=135.0)
    loc_b = Location(name="Posto B", is_hub=False, lat=35.0001, lon=135.0001)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    def boom(*args, **kwargs):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "compare_places", boom)

    response = client.post(f"/ui/audit/ai/compare/{loc_a.id}/{loc_b.id}")
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_audit_ai_compare_returns_404_for_missing_location(client, session):
    loc = Location(name="Posto A", is_hub=False, lat=35.0, lon=135.0)
    session.add(loc)
    session.commit()
    session.refresh(loc)

    response = client.post(f"/ui/audit/ai/compare/{loc.id}/does-not-exist")
    assert response.status_code == 404


def test_ui_audit_ai_split_shows_a_proposal_per_reel(client, session, monkeypatch):
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    session.add(kamakura)
    session.commit()
    session.refresh(kamakura)

    link = "https://www.instagram.com/reel/same-link/"
    reel_a = Reel(link=link, location_id=kamakura.id, note="Grande statua del Buddha a Kotoku-in.")
    reel_b = Reel(link=link, location_id=kamakura.id, note="Tempio famoso per i giardini e la vista.")
    session.add(reel_a)
    session.add(reel_b)
    session.commit()
    session.refresh(reel_a)
    session.refresh(reel_b)

    def fake_categorize(hub_names, categories, messages):
        note = messages[0]["content"]
        if "Kotoku-in" in note:
            return {
                "place_name": "Kotoku-in Daibutsu", "near_hub": None, "types": [],
                "note": note, "confidence": "high", "question": None,
                "lat": 35.3166, "lon": 139.5360,
            }
        return {
            "place_name": "Hase-dera", "near_hub": None, "types": [],
            "note": note, "confidence": "high", "question": None,
            "lat": 35.3122, "lon": 139.5339,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    response = client.post(f"/ui/audit/ai/split/{kamakura.id}", data={"link": link})
    assert response.status_code == 200
    assert "Kotoku-in Daibutsu" in response.text
    assert "Hase-dera" in response.text
    assert "Grande statua del Buddha a Kotoku-in." in response.text
    assert "Tempio famoso per i giardini e la vista." in response.text


def test_ui_audit_ai_split_handles_provider_error_for_one_reel(client, session, monkeypatch):
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    session.add(kamakura)
    session.commit()
    session.refresh(kamakura)

    link = "https://www.instagram.com/reel/same-link/"
    session.add(Reel(link=link, location_id=kamakura.id, note="Nota A"))
    session.add(Reel(link=link, location_id=kamakura.id, note="Nota B"))
    session.commit()

    def boom(hub_names, categories, messages):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post(f"/ui/audit/ai/split/{kamakura.id}", data={"link": link})
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_audit_ai_split_apply_creates_new_locations_and_reassigns_reels(client, session):
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    session.add(kamakura)
    session.commit()
    session.refresh(kamakura)

    reel_a = Reel(link="https://instagram.com/reel/x", location_id=kamakura.id, note="Nota Kotoku-in")
    reel_b = Reel(link="https://instagram.com/reel/x", location_id=kamakura.id, note="Nota Hase-dera")
    session.add(reel_a)
    session.add(reel_b)
    session.commit()
    session.refresh(reel_a)
    session.refresh(reel_b)

    place_a = json.dumps({
        "reel_id": reel_a.id, "place_name": "Kotoku-in Daibutsu", "note": "Nota Kotoku-in",
        "lat": 35.3166, "lon": 139.5360, "confidence": "high",
        "resolution_location_id": "", "resolution_hub_id": NEW_HUB_SENTINEL,
    })
    place_b = json.dumps({
        "reel_id": reel_b.id, "place_name": "Hase-dera", "note": "Nota Hase-dera",
        "lat": 35.3122, "lon": 139.5339, "confidence": "high",
        "resolution_location_id": "", "resolution_hub_id": NEW_HUB_SENTINEL,
    })

    response = client.post("/ui/audit/ai/split/apply", data={"place_json": [place_a, place_b]})
    assert response.status_code == 200

    session.refresh(reel_a)
    session.refresh(reel_b)
    assert reel_a.location_id != kamakura.id
    assert reel_b.location_id != kamakura.id
    assert reel_a.location_id != reel_b.location_id

    kotoku = session.get(Location, reel_a.location_id)
    hase = session.get(Location, reel_b.location_id)
    assert kotoku.name == "Kotoku-in Daibutsu"
    assert hase.name == "Hase-dera"
    assert kotoku.is_hub is True
    assert hase.is_hub is True


def test_ui_audit_ai_split_apply_can_reassign_to_an_existing_location(client, session):
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    existing = Location(name="Komachi Street", is_hub=False, lat=35.319, lon=139.549)
    session.add(kamakura)
    session.add(existing)
    session.commit()
    session.refresh(kamakura)
    session.refresh(existing)

    reel = Reel(link="https://instagram.com/reel/x", location_id=kamakura.id, note="Nota")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    place = json.dumps({
        "reel_id": reel.id, "place_name": "Komachi Street", "note": "Nota",
        "lat": None, "lon": None, "confidence": None,
        "resolution_location_id": existing.id, "resolution_hub_id": "",
    })

    response = client.post("/ui/audit/ai/split/apply", data={"place_json": [place]})
    assert response.status_code == 200

    session.refresh(reel)
    assert reel.location_id == existing.id


def test_ui_audit_ai_split_apply_validates_whole_batch_before_reassigning_any(client, session):
    kamakura = Location(name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)
    session.add(kamakura)
    session.commit()
    session.refresh(kamakura)

    reel_a = Reel(link="https://instagram.com/reel/x", location_id=kamakura.id, note="Nota A")
    reel_b = Reel(link="https://instagram.com/reel/x", location_id=kamakura.id, note="Nota B")
    session.add(reel_a)
    session.add(reel_b)
    session.commit()
    session.refresh(reel_a)
    session.refresh(reel_b)

    valid_place = json.dumps({
        "reel_id": reel_a.id, "place_name": "Kotoku-in Daibutsu", "note": "Nota A",
        "lat": 35.3166, "lon": 139.5360, "confidence": "high",
        "resolution_location_id": "", "resolution_hub_id": NEW_HUB_SENTINEL,
    })
    invalid_place = json.dumps({
        "reel_id": reel_b.id, "place_name": "Hase-dera", "note": "Nota B",
        "lat": 35.3122, "lon": 139.5339, "confidence": "high",
        "resolution_location_id": "", "resolution_hub_id": "",
    })

    response = client.post("/ui/audit/ai/split/apply", data={"place_json": [valid_place, invalid_place]})
    assert response.status_code == 400

    session.refresh(reel_a)
    assert reel_a.location_id == kamakura.id


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

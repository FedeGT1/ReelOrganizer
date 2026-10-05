from app.location_matching import haversine_distance_m, normalize_place_name


def test_normalize_place_name_lowercases_and_strips():
    assert normalize_place_name("  Ichiran Ramen  ") == "ichiran ramen"


def test_normalize_place_name_strips_diacritics():
    assert normalize_place_name("Kōtoku-in") == "kotoku in"


def test_normalize_place_name_removes_parenthetical_content():
    assert normalize_place_name("Surugaya Akihabara (駿河屋秋葉原)") == "surugaya akihabara"


def test_normalize_place_name_collapses_punctuation_variants_to_the_same_string():
    assert normalize_place_name("Surugaya - Akihabara") == normalize_place_name(
        "Surugaya Akihabara (駿河屋秋葉原)"
    )


def test_normalize_place_name_empty_string_stays_empty():
    assert normalize_place_name("") == ""


def test_normalize_place_name_short_name_substring_check_against_hub_label():
    # Exercised directly here because it's the exact relationship Task 2's
    # tier-1 hub-containment check relies on.
    assert normalize_place_name("Tokyo") in normalize_place_name("Tokyo / Kanto")
    assert normalize_place_name("Hakone-Yumoto Eva Store") not in normalize_place_name("Hakone")


def test_haversine_distance_m_is_zero_for_identical_points():
    assert haversine_distance_m(35.6762, 139.6503, 35.6762, 139.6503) == 0.0


def test_haversine_distance_m_matches_known_tokyo_kyoto_distance():
    # Tokyo Station to Kyoto Station is ~368km in a straight line.
    distance = haversine_distance_m(35.6812, 139.7671, 34.9858, 135.7581)
    assert 360_000 < distance < 376_000


def test_haversine_distance_m_is_symmetric():
    a = haversine_distance_m(35.6762, 139.6503, 35.0116, 135.7681)
    b = haversine_distance_m(35.0116, 135.7681, 35.6762, 139.6503)
    assert a == b


from app.location_matching import NEW_HUB_SENTINEL, resolve_place
from app.models import Location


def _add(session, **kwargs):
    loc = Location(**kwargs)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def test_resolve_place_exact_normalized_match_is_auto(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "nishiki market", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id
    assert resolution.requires_confirmation is False


def test_resolve_place_formatting_duplicate_matches_via_normalization(session):
    loc = _add(session, name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77)

    resolution = resolve_place(session, "Surugaya Akihabara (駿河屋秋葉原)", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id


def test_resolve_place_short_name_matches_containing_hub_label(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Tokyo", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == hub.id


def test_resolve_place_does_not_match_hub_when_hub_name_is_only_a_substring_of_new_place(session):
    _add(session, name="Hakone", is_hub=True, lat=35.2323, lon=139.1069)

    resolution = resolve_place(
        session, "Hakone-Yumoto Eva Store", "Hakone", 35.20139, 139.04361
    )

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_similar_name_and_close_distance_is_auto(session):
    # Same real shop, AI phrased the name slightly differently this time.
    # "Ichiran Ramen Shibuya Ten" normalizes to a DIFFERENT string than
    # "Ichiran Ramen Shibuya" (tier 1 must NOT fire here) but scores a high
    # SequenceMatcher ratio (~0.91) against it, so this exercises tier 2
    # specifically -- not tier 1 by coincidence.
    loc = _add(session, name="Ichiran Ramen Shibuya", is_hub=False, lat=35.6590, lon=139.7005)

    resolution = resolve_place(session, "Ichiran Ramen Shibuya Ten", None, 35.6591, 139.7006)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id


def test_resolve_place_close_distance_but_unrelated_name_requires_confirmation(session):
    # Two different shops in the same building: same coordinates, unrelated names.
    _add(session, name="Starbucks Shibuya", is_hub=False, lat=35.6590, lon=139.7005)

    resolution = resolve_place(session, "Pokémon Center Shibuya", None, 35.6590, 139.7005)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None
    assert resolution.requires_confirmation is True


def test_resolve_place_far_distance_returns_ranked_candidate_not_auto_match(session):
    # Kamakura town center vs. the Daibutsu (Kotoku-in), ~2.5km apart.
    kamakura = _add(session, name="Kamakura", is_hub=False, lat=35.3193, lon=139.5466)

    resolution = resolve_place(session, "Kotoku-in Daibutsu", None, 35.3166, 139.5360)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None
    assert [c.id for c in resolution.place_candidates] == [kamakura.id]


def test_resolve_place_candidates_default_to_new_place_not_pre_selected(session):
    _add(session, name="Some Other Shop", is_hub=False, lat=35.0, lon=135.0)

    resolution = resolve_place(session, "Unrelated New Shop", None, 35.0001, 135.0001)

    # Close distance (~15m) but unrelated name: shown as a candidate, never auto-picked.
    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_empty_place_name_never_auto_matches(session):
    _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "", None, None, None)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_candidates_capped_and_sorted_by_distance(session):
    for i in range(7):
        _add(session, name=f"Shop {i}", is_hub=False, lat=35.0 + i * 0.001, lon=135.0)

    resolution = resolve_place(session, "New Nearby Shop", None, 35.0, 135.0)

    assert len(resolution.place_candidates) == 5
    distances = [c.distance_m for c in resolution.place_candidates]
    assert distances == sorted(distances)


def test_resolve_place_hub_exact_match_is_auto(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Nikko", "Tokyo / Kanto", 36.7198, 139.6982)

    assert resolution.hub_tier == "auto"
    assert resolution.hub_id == hub.id


def test_resolve_place_hub_no_match_is_ambiguous_with_options(session):
    hub = _add(session, name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)

    resolution = resolve_place(session, "Nikko", "Somewhere Else", 36.7198, 139.6982)

    assert resolution.hub_tier == "ambiguous"
    assert resolution.hub_id is None
    assert [h.id for h in resolution.hub_options] == [hub.id]


def test_resolve_place_hub_missing_near_hub_is_ambiguous(session):
    resolution = resolve_place(session, "Nikko", None, 36.7198, 139.6982)

    assert resolution.hub_tier == "ambiguous"
    assert resolution.hub_id is None


def test_resolve_place_requires_confirmation_false_when_place_auto_matched(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "Nishiki Market", "Does Not Exist", None, None)

    assert resolution.place_location_id == loc.id
    assert resolution.requires_confirmation is False


def test_resolve_place_requires_confirmation_true_when_hub_ambiguous_even_without_candidates(session):
    resolution = resolve_place(session, "Brand New City Area", "Unknown Hub", None, None)

    assert resolution.place_candidates == []
    assert resolution.hub_tier == "ambiguous"
    assert resolution.requires_confirmation is True


def test_resolve_place_new_hub_sentinel_is_a_non_empty_string():
    assert NEW_HUB_SENTINEL
    assert isinstance(NEW_HUB_SENTINEL, str)

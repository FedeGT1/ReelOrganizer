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

from app.models import Location, Reel
from app.reel_links import extract_reel_shortcode, find_duplicate_reel, reel_link_key


def test_extract_reel_shortcode_from_plain_link():
    assert extract_reel_shortcode("https://instagram.com/reel/ABC123/") == "ABC123"


def test_extract_reel_shortcode_ignores_www_and_query_string():
    assert (
        extract_reel_shortcode("https://www.instagram.com/reel/ABC123/?igshid=xyz")
        == "ABC123"
    )


def test_extract_reel_shortcode_handles_p_and_reels_paths():
    assert extract_reel_shortcode("https://instagram.com/p/XYZ999/") == "XYZ999"
    assert extract_reel_shortcode("https://instagram.com/reels/XYZ999/") == "XYZ999"


def test_extract_reel_shortcode_returns_none_for_unrelated_link():
    assert extract_reel_shortcode("https://example.com/something") is None


def test_reel_link_key_falls_back_to_raw_link_when_not_instagram():
    assert reel_link_key("https://example.com/something") == "https://example.com/something"


def test_reel_link_key_treats_link_variants_as_equal():
    key_a = reel_link_key("https://instagram.com/reel/ABC123/")
    key_b = reel_link_key("https://www.instagram.com/reel/ABC123/?igshid=xyz")
    assert key_a == key_b


def test_find_duplicate_reel_matches_normalized_variant(session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/ABC123/", location_id=hub.id))
    session.commit()

    found = find_duplicate_reel(session, "https://www.instagram.com/reel/ABC123/?igshid=xyz")
    assert found is not None
    assert found.location_id == hub.id


def test_find_duplicate_reel_returns_none_when_no_match(session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/ABC123/", location_id=hub.id))
    session.commit()

    assert find_duplicate_reel(session, "https://instagram.com/reel/OTHER/") is None

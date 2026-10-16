import re
from datetime import datetime, timedelta

from app.models import Location, Reel

T0 = datetime(2026, 10, 1, 12, 0, 0)


def _loc(session, user_id, name, is_hub=True, parent_id=None):
    loc = Location(name=name, is_hub=is_hub, parent_id=parent_id, user_id=user_id)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _reel(session, user_id, loc, minutes):
    reel = Reel(
        link=f"https://example.com/{loc.name}/{minutes}",
        location_id=loc.id,
        user_id=user_id,
        created_at=T0 + timedelta(minutes=minutes),
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)
    return reel


def _sections(html: str) -> list[str]:
    parts = html.split('<section class="reel-group"')[1:]
    return ['<section class="reel-group"' + p.split("</section>")[0] for p in parts]


def test_each_place_gets_one_section_with_its_cards(client, session, test_user_id):
    fushimi = _loc(session, test_user_id, "Fushimi Inari")
    nishiki = _loc(session, test_user_id, "Nishiki Market")
    a = _reel(session, test_user_id, fushimi, 1)
    b = _reel(session, test_user_id, nishiki, 2)
    c = _reel(session, test_user_id, fushimi, 3)

    sections = _sections(client.get("/ui/reels").text)

    assert len(sections) == 2
    assert f'data-location-id="{fushimi.id}"' in sections[0]
    assert f'id="reel-{a.id}"' in sections[0] and f'id="reel-{c.id}"' in sections[0]
    assert f'id="reel-{b.id}"' not in sections[0]
    assert f'data-location-id="{nishiki.id}"' in sections[1]
    assert f'id="reel-{b.id}"' in sections[1]


def test_header_shows_place_name_and_reel_count(client, session, test_user_id):
    fushimi = _loc(session, test_user_id, "Fushimi Inari")
    for minutes in (1, 2, 3):
        _reel(session, test_user_id, fushimi, minutes)

    section = _sections(client.get("/ui/reels").text)[0]
    header = re.search(r'<h3 class="reel-group-header">(.*?)</h3>', section, re.S).group(1)

    assert "Fushimi Inari" in header
    assert re.search(r'class="reel-group-count">\s*3\s*<', header)


def test_satellite_header_includes_the_hub_and_a_hub_header_does_not(client, session, test_user_id):
    kyoto = _loc(session, test_user_id, "Kyoto")
    fushimi = _loc(session, test_user_id, "Fushimi Inari", is_hub=False, parent_id=kyoto.id)
    _reel(session, test_user_id, fushimi, 2)
    _reel(session, test_user_id, kyoto, 1)

    sections = _sections(client.get("/ui/reels").text)
    headers = [re.search(r'<h3 class="reel-group-header">(.*?)</h3>', s, re.S).group(1) for s in sections]

    assert "Fushimi Inari" in headers[0] and "Kyoto" in headers[0]
    assert "·" in headers[0]
    assert "Kyoto" in headers[1] and "·" not in headers[1]


def test_a_place_with_one_reel_still_has_a_header(client, session, test_user_id):
    solo = _loc(session, test_user_id, "Solo spot")
    _reel(session, test_user_id, solo, 1)

    sections = _sections(client.get("/ui/reels").text)

    assert len(sections) == 1
    assert "Solo spot" in sections[0]
    assert 'class="reel-group-header"' in sections[0]


def test_cards_stay_standalone_list_items(client, session, test_user_id):
    loc = _loc(session, test_user_id, "Anywhere")
    reel = _reel(session, test_user_id, loc, 1)

    section = _sections(client.get("/ui/reels").text)[0]

    assert f'<li id="reel-{reel.id}">' in section
    assert '<ul class="reel-list">' in section


def test_empty_list_renders_no_group(client):
    html = client.get("/ui/reels").text

    assert _sections(html) == []


def test_location_filter_banner_is_kept(client, session, test_user_id):
    kyoto = _loc(session, test_user_id, "Kyoto")
    _reel(session, test_user_id, kyoto, 1)

    html = client.get(f"/ui/reels?location_id={kyoto.id}").text

    assert "reel-filter-banner" in html
    assert len(_sections(html)) == 1


def test_header_escapes_place_names(client, session, test_user_id):
    risky = _loc(session, test_user_id, "<b>x</b> & co")
    _reel(session, test_user_id, risky, 1)

    section = _sections(client.get("/ui/reels").text)[0]

    assert "<b>x</b>" not in section
    assert "&lt;b&gt;x&lt;/b&gt;" in section

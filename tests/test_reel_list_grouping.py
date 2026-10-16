from datetime import datetime, timedelta

from app.models import Category, Location, Reel, ReelType
from app.routers.reels import _reel_list_context

T0 = datetime(2026, 10, 1, 12, 0, 0)


def _loc(session, user_id, name, is_hub=True, parent_id=None):
    loc = Location(name=name, is_hub=is_hub, parent_id=parent_id, user_id=user_id)
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc


def _reel(session, user_id, loc, minutes, link=None):
    reel = Reel(
        link=link or f"https://example.com/{loc.name}/{minutes}",
        location_id=loc.id,
        user_id=user_id,
        created_at=T0 + timedelta(minutes=minutes),
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)
    return reel


def _groups(session, user_id, **kwargs):
    return _reel_list_context(session, user_id, **kwargs)["groups"]


def test_non_adjacent_reels_of_same_place_end_up_in_one_group(session, test_user_id):
    fushimi = _loc(session, test_user_id, "Fushimi Inari")
    nishiki = _loc(session, test_user_id, "Nishiki Market")
    _reel(session, test_user_id, fushimi, 1)
    _reel(session, test_user_id, nishiki, 2)
    _reel(session, test_user_id, fushimi, 3)

    groups = _groups(session, test_user_id)

    assert [g["location_id"] for g in groups] == [fushimi.id, nishiki.id]
    assert [g["count"] for g in groups] == [2, 1]
    assert len(groups[0]["reels"]) == 2


def test_groups_are_ordered_by_most_recent_reel_first(session, test_user_id):
    old = _loc(session, test_user_id, "Old place")
    mid = _loc(session, test_user_id, "Mid place")
    new = _loc(session, test_user_id, "New place")
    _reel(session, test_user_id, old, 1)
    _reel(session, test_user_id, new, 2)
    _reel(session, test_user_id, mid, 3)
    _reel(session, test_user_id, old, 10)

    groups = _groups(session, test_user_id)

    assert [g["location_id"] for g in groups] == [old.id, mid.id, new.id]


def test_reels_inside_a_group_are_newest_first(session, test_user_id):
    loc = _loc(session, test_user_id, "Kyoto spot")
    a = _reel(session, test_user_id, loc, 1)
    b = _reel(session, test_user_id, loc, 5)
    c = _reel(session, test_user_id, loc, 3)

    groups = _groups(session, test_user_id)

    assert [r["id"] for r in groups[0]["reels"]] == [b.id, c.id, a.id]


def test_equal_timestamps_give_a_stable_order_by_place_name(session, test_user_id):
    zeta = _loc(session, test_user_id, "Zeta")
    alfa = _loc(session, test_user_id, "Alfa")
    _reel(session, test_user_id, zeta, 4)
    _reel(session, test_user_id, alfa, 4)

    first = [g["name"] for g in _groups(session, test_user_id)]
    second = [g["name"] for g in _groups(session, test_user_id)]

    assert first == ["Alfa", "Zeta"]
    assert second == first


def test_satellite_group_carries_its_hub_name_and_a_hub_group_does_not(session, test_user_id):
    kyoto = _loc(session, test_user_id, "Kyoto")
    fushimi = _loc(session, test_user_id, "Fushimi Inari", is_hub=False, parent_id=kyoto.id)
    _reel(session, test_user_id, fushimi, 1)
    _reel(session, test_user_id, kyoto, 2)

    by_id = {g["location_id"]: g for g in _groups(session, test_user_id)}

    assert by_id[fushimi.id]["name"] == "Fushimi Inari"
    assert by_id[fushimi.id]["hub_name"] == "Kyoto"
    assert by_id[kyoto.id]["name"] == "Kyoto"
    assert by_id[kyoto.id]["hub_name"] is None


def test_a_place_with_a_single_reel_still_gets_a_group(session, test_user_id):
    loc = _loc(session, test_user_id, "Solo")
    _reel(session, test_user_id, loc, 1)

    groups = _groups(session, test_user_id)

    assert len(groups) == 1
    assert groups[0]["count"] == 1


def test_hub_filter_keeps_one_group_per_satellite(session, test_user_id):
    kyoto = _loc(session, test_user_id, "Kyoto")
    osaka = _loc(session, test_user_id, "Osaka")
    fushimi = _loc(session, test_user_id, "Fushimi Inari", is_hub=False, parent_id=kyoto.id)
    nishiki = _loc(session, test_user_id, "Nishiki Market", is_hub=False, parent_id=kyoto.id)
    _reel(session, test_user_id, fushimi, 1)
    _reel(session, test_user_id, nishiki, 2)
    _reel(session, test_user_id, fushimi, 3)
    _reel(session, test_user_id, osaka, 4)

    groups = _groups(session, test_user_id, location_id=kyoto.id)

    assert [g["location_id"] for g in groups] == [fushimi.id, nishiki.id]
    assert [g["count"] for g in groups] == [2, 1]


def test_type_and_text_filters_apply_before_grouping(session, test_user_id):
    session.add(Category(user_id=test_user_id, key="food", label="Food", icon="F"))
    session.commit()
    a = _loc(session, test_user_id, "Alpha")
    b = _loc(session, test_user_id, "Beta")
    r1 = _reel(session, test_user_id, a, 1)
    _reel(session, test_user_id, a, 2)
    _reel(session, test_user_id, b, 3)
    session.add(ReelType(reel_id=r1.id, type="food"))
    session.commit()

    by_type = _groups(session, test_user_id, type_values=["food"])
    by_text = _groups(session, test_user_id, q="beta")

    assert [(g["location_id"], g["count"]) for g in by_type] == [(a.id, 1)]
    assert [(g["location_id"], g["count"]) for g in by_text] == [(b.id, 1)]


def test_other_users_reels_are_not_grouped(session, test_user_id):
    mine = _loc(session, test_user_id, "Mine")
    theirs = _loc(session, "someone-else", "Theirs")
    _reel(session, test_user_id, mine, 1)
    _reel(session, "someone-else", theirs, 2)

    groups = _groups(session, test_user_id)

    assert [g["location_id"] for g in groups] == [mine.id]


def test_api_reels_keeps_its_current_order(client, session, test_user_id):
    a = _loc(session, test_user_id, "Alpha")
    b = _loc(session, test_user_id, "Beta")
    r1 = _reel(session, test_user_id, a, 1)
    r2 = _reel(session, test_user_id, b, 2)
    r3 = _reel(session, test_user_id, a, 3)

    response = client.get("/api/reels")

    assert [r["id"] for r in response.json()] == [r1.id, r2.id, r3.id]

from app.models import Reel, ReelType
from app.routers.categories import reel_ids_matching_types


def test_reel_ids_matching_types_returns_none_when_no_types_given(session):
    assert reel_ids_matching_types(session, []) is None


def test_reel_ids_matching_types_matches_reels_with_all_given_types(session):
    reel_both = Reel(link="https://instagram.com/reel/both", location_id="loc-1")
    reel_food_only = Reel(link="https://instagram.com/reel/food", location_id="loc-1")
    session.add(reel_both)
    session.add(reel_food_only)
    session.commit()
    session.refresh(reel_both)
    session.refresh(reel_food_only)
    session.add(ReelType(reel_id=reel_both.id, type="food"))
    session.add(ReelType(reel_id=reel_both.id, type="shopping"))
    session.add(ReelType(reel_id=reel_food_only.id, type="food"))
    session.commit()

    result = reel_ids_matching_types(session, ["food", "shopping"])

    assert result == {reel_both.id}


def test_reel_ids_matching_types_returns_empty_set_when_nothing_matches_all(session):
    reel = Reel(link="https://instagram.com/reel/x", location_id="loc-1")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    result = reel_ids_matching_types(session, ["food", "culture"])

    assert result == set()

from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Category, Location
from app.seed import seed_user_if_empty


def test_seed_user_if_empty_creates_hubs_and_satellites():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")

        hubs = session.exec(
            select(Location).where(Location.is_hub == True, Location.user_id == "user-1")
        ).all()
        satellites = session.exec(
            select(Location).where(Location.is_hub == False, Location.user_id == "user-1")
        ).all()

        assert len(hubs) == 10
        assert len(satellites) == 10
        tokyo = next(h for h in hubs if h.name == "Tokyo / Kanto")
        nikko = next(s for s in satellites if s.name == "Nikko")
        assert nikko.parent_id == tokyo.id


def test_seed_user_if_empty_is_idempotent_per_user():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")
        seed_user_if_empty(session, "user-1")
        locations = session.exec(select(Location).where(Location.user_id == "user-1")).all()
        assert len(locations) == 20


def test_seed_user_if_empty_creates_default_categories_scoped_to_user():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")

        categories = session.exec(select(Category).where(Category.user_id == "user-1")).all()
        assert {c.key for c in categories} == {
            "food", "culture", "nature", "shopping", "stay", "transport", "experience",
        }
        food = next(c for c in categories if c.key == "food")
        assert food.label == "Cibo"
        assert food.icon == "🍜"


def test_seed_user_if_empty_does_not_touch_another_users_data():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")
        seed_user_if_empty(session, "user-2")

        user_1_locations = session.exec(select(Location).where(Location.user_id == "user-1")).all()
        user_2_locations = session.exec(select(Location).where(Location.user_id == "user-2")).all()
        assert len(user_1_locations) == 20
        assert len(user_2_locations) == 20

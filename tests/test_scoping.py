from sqlmodel import SQLModel, Session, create_engine

from app.models import Category, Location
from app.scoping import get_owned, get_owned_category, user_query


def _engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_user_query_returns_only_rows_for_that_user():
    engine = _engine()
    with Session(engine) as session:
        session.add(Location(name="A", is_hub=True, user_id="user-1"))
        session.add(Location(name="B", is_hub=True, user_id="user-2"))
        session.commit()

        results = session.exec(user_query(Location, "user-1")).all()

        assert [loc.name for loc in results] == ["A"]


def test_get_owned_returns_row_when_owned():
    engine = _engine()
    with Session(engine) as session:
        loc = Location(name="A", is_hub=True, user_id="user-1")
        session.add(loc)
        session.commit()
        session.refresh(loc)

        result = get_owned(session, Location, loc.id, "user-1")

        assert result is not None
        assert result.id == loc.id


def test_get_owned_returns_none_when_owned_by_another_user():
    engine = _engine()
    with Session(engine) as session:
        loc = Location(name="A", is_hub=True, user_id="user-1")
        session.add(loc)
        session.commit()
        session.refresh(loc)

        assert get_owned(session, Location, loc.id, "user-2") is None


def test_get_owned_returns_none_when_missing():
    engine = _engine()
    with Session(engine) as session:
        assert get_owned(session, Location, "does-not-exist", "user-1") is None


def test_get_owned_category_scopes_by_composite_key():
    engine = _engine()
    with Session(engine) as session:
        session.add(Category(user_id="user-1", key="food", label="Cibo", icon="🍜"))
        session.add(Category(user_id="user-2", key="food", label="Food", icon="🍔"))
        session.commit()

        own = get_owned_category(session, "food", "user-1")
        other = get_owned_category(session, "food", "user-3")

        assert own is not None and own.label == "Cibo"
        assert other is None

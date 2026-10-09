import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from app.auth import verify_password
from app.models import Category, Location, User
from scripts.create_user import UsernameTakenError, create_user


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_user_persists_hashed_password(session):
    user = create_user(session, "alice", "s3cret")

    stored = session.get(User, user.id)
    assert stored.username == "alice"
    assert verify_password("s3cret", stored.password_hash) is True


def test_create_user_seeds_default_hubs_and_categories(session):
    user = create_user(session, "alice", "s3cret")

    locations = session.exec(select(Location).where(Location.user_id == user.id)).all()
    categories = session.exec(select(Category).where(Category.user_id == user.id)).all()
    assert len(locations) == 20
    assert len(categories) == 7


def test_create_user_rejects_duplicate_username(session):
    create_user(session, "alice", "s3cret")

    with pytest.raises(UsernameTakenError):
        create_user(session, "alice", "different-password")

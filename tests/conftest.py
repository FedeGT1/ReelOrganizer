import os

os.environ["AUTH_USERNAME"] = "testuser"
os.environ["AUTH_PASSWORD"] = "testpass"
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-for-production"

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient


@pytest.fixture(name="session")
def session_fixture():
    from app.auth import hash_password
    from app.models import User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="testuser", password_hash=hash_password("testpass")))
        session.commit()
        yield session


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.auth import rate_limiter

    rate_limiter.clear_all()
    yield
    rate_limiter.clear_all()


def _build_client(session: Session) -> TestClient:
    from app.db import get_session
    from app.main import app

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(name="client")
def client_fixture(session: Session):
    client = _build_client(session)
    client.post("/login", data={"username": "testuser", "password": "testpass"})
    yield client
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture(name="test_user_id")
def test_user_id_fixture(session: Session) -> str:
    from app.models import User

    return session.exec(select(User).where(User.username == "testuser")).first().id


@pytest.fixture(name="anon_client")
def anon_client_fixture(session: Session):
    client = _build_client(session)
    yield client
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture(name="second_user_client")
def second_user_client_fixture(session: Session):
    from app.auth import hash_password
    from app.models import User
    from app.seed import seed_user_if_empty

    user = User(username="seconduser", password_hash=hash_password("secondpass"))
    session.add(user)
    session.commit()
    session.refresh(user)
    # Mirrors scripts/create_user.py's own create_user(): seed default hubs
    # and categories right after the account is created, the same way a
    # real admin-created account would start out.
    seed_user_if_empty(session, user.id)

    client = _build_client(session)
    client.post("/login", data={"username": "seconduser", "password": "secondpass"})
    yield client
    from app.main import app

    app.dependency_overrides.clear()

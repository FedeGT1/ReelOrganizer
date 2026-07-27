import os

os.environ["AUTH_USERNAME"] = "testuser"
os.environ["AUTH_PASSWORD"] = "testpass"
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-for-production"

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
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


@pytest.fixture(name="anon_client")
def anon_client_fixture(session: Session):
    client = _build_client(session)
    yield client
    from app.main import app

    app.dependency_overrides.clear()

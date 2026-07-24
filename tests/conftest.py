import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

from app.models import Category
from app.seed import DEFAULT_CATEGORIES


@pytest.fixture(name="session")
def session_fixture(request):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed only categories for tests that use _reel_list_context (ai tests).
        # This allows ai tests to access the taxonomy without breaking tests
        # that expect an empty database (like test_categories_api).
        if "ai" in request.node.name:
            if session.exec(select(Category)).first() is None:
                for key, label, icon, color in DEFAULT_CATEGORIES:
                    session.add(Category(key=key, label=label, icon=icon, color=color))
                session.commit()
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    # Imported lazily: app.main doesn't exist until Task 7. Tasks 2-6 use
    # only the `session` fixture, so collection must not require app.main.
    from app.db import get_session
    from app.main import app

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

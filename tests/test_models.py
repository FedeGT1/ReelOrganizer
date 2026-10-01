from datetime import datetime

from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Location


def test_create_hub_and_satellite_location():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
        session.add(satellite)
        session.commit()
        session.refresh(satellite)

        assert hub.id is not None
        assert satellite.parent_id == hub.id
        assert satellite.is_hub is False


def test_create_reel_with_types():
    from app.models import Reel, ReelType

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        reel = Reel(link="https://instagram.com/reel/abc", location_id=hub.id, note="Ramen spot")
        session.add(reel)
        session.commit()
        session.refresh(reel)

        session.add(ReelType(reel_id=reel.id, type="food"))
        session.add(ReelType(reel_id=reel.id, type="culture"))
        session.commit()

        assert isinstance(reel.created_at, datetime)
        types = session.exec(
            select(ReelType).where(ReelType.reel_id == reel.id)
        ).all()
        assert {t.type for t in types} == {"food", "culture"}


def test_create_ai_session_with_messages():
    from app.models import AiMessage, AiSession

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ai_session = AiSession()
        session.add(ai_session)
        session.commit()
        session.refresh(ai_session)

        session.add(AiMessage(session_id=ai_session.id, role="user", content="Un reel di ramen a Tokyo"))
        session.commit()

        messages = session.exec(
            select(AiMessage).where(AiMessage.session_id == ai_session.id)
        ).all()
        assert len(messages) == 1
        assert messages[0].role == "user"


def test_create_ask_session_with_messages():
    from app.models import AskMessage, AskSession

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        ask_session = AskSession(location_id=hub.id, category_key="food")
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

        session.add(AskMessage(session_id=ask_session.id, role="user", content="Cosa mi consigli?"))
        session.commit()

        messages = session.exec(
            select(AskMessage).where(AskMessage.session_id == ask_session.id)
        ).all()
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert ask_session.location_id == hub.id
        assert ask_session.category_key == "food"


def test_create_ask_session_with_no_scope():
    from app.models import AskSession

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ask_session = AskSession()
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

        assert ask_session.location_id is None
        assert ask_session.category_key is None


def test_create_category():
    from app.models import Category

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        category = Category(key="food", label="Cibo", icon="🍜", color="#A63A2E")
        session.add(category)
        session.commit()
        session.refresh(category)

        assert category.key == "food"
        assert category.label == "Cibo"
        assert isinstance(category.created_at, datetime)

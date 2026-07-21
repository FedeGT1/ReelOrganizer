from datetime import datetime

from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Location


def test_create_hub_and_satellite_location():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
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
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
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

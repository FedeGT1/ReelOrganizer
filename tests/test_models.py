from sqlmodel import SQLModel, Session, create_engine

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

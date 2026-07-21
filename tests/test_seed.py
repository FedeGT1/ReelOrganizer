from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Location
from app.seed import seed_if_empty


def test_seed_if_empty_creates_hubs_and_satellites():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)

        hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
        satellites = session.exec(select(Location).where(Location.is_hub == False)).all()

        assert len(hubs) == 9
        assert len(satellites) == 10
        tokyo = next(h for h in hubs if h.name == "Tokyo / Kanto")
        nikko = next(s for s in satellites if s.name == "Nikko")
        assert nikko.parent_id == tokyo.id


def test_seed_if_empty_is_idempotent():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)
        seed_if_empty(session)
        all_locations = session.exec(select(Location)).all()
        assert len(all_locations) == 19

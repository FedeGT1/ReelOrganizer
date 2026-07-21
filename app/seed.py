from sqlmodel import Session, select

from app.models import Location

HUBS = [
    ("Sapporo / Hokkaido", 100.0, 50.0),
    ("Sendai / Tohoku", 150.0, 150.0),
    ("Tokyo / Kanto", 200.0, 250.0),
    ("Nagoya / Chubu", 180.0, 320.0),
    ("Kyoto - Osaka / Kansai", 150.0, 380.0),
    ("Hiroshima / Chugoku", 100.0, 420.0),
    ("Matsuyama / Shikoku", 120.0, 460.0),
    ("Fukuoka / Kyushu", 80.0, 480.0),
    ("Okinawa", 60.0, 560.0),
]

SATELLITES = [
    ("Nikko", "Tokyo / Kanto"),
    ("Kamakura", "Tokyo / Kanto"),
    ("Hakone", "Tokyo / Kanto"),
    ("Kawagoe", "Tokyo / Kanto"),
    ("Nara", "Kyoto - Osaka / Kansai"),
    ("Uji", "Kyoto - Osaka / Kansai"),
    ("Himeji", "Kyoto - Osaka / Kansai"),
    ("Miyajima", "Hiroshima / Chugoku"),
    ("Otaru", "Sapporo / Hokkaido"),
    ("Dazaifu", "Fukuoka / Kyushu"),
]


def seed_if_empty(session: Session) -> None:
    existing = session.exec(select(Location)).first()
    if existing is not None:
        return

    hub_by_name: dict[str, Location] = {}
    for name, x, y in HUBS:
        hub = Location(name=name, is_hub=True, x=x, y=y)
        session.add(hub)
        session.flush()
        hub_by_name[name] = hub

    for name, hub_name in SATELLITES:
        parent = hub_by_name[hub_name]
        session.add(Location(name=name, is_hub=False, parent_id=parent.id))

    session.commit()

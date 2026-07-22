from sqlmodel import Session, select

from app.models import Location

HUBS = [
    ("Sapporo / Hokkaido", 43.0621, 141.3544, False),
    ("Sendai / Tohoku", 38.2682, 140.8694, False),
    ("Tokyo / Kanto", 35.6762, 139.6503, False),
    ("Nagoya / Chubu", 35.1815, 136.9066, False),
    ("Kyoto - Osaka / Kansai", 34.85, 135.60, False),
    ("Hiroshima / Chugoku", 34.3853, 132.4553, False),
    ("Matsuyama / Shikoku", 33.8392, 132.7657, False),
    ("Fukuoka / Kyushu", 33.5904, 130.4017, False),
    ("Okinawa", 26.2124, 127.6809, True),
]

SATELLITES = [
    ("Nikko", "Tokyo / Kanto", 36.7199, 139.6982),
    ("Kamakura", "Tokyo / Kanto", 35.3193, 139.5466),
    ("Hakone", "Tokyo / Kanto", 35.2323, 139.1069),
    ("Kawagoe", "Tokyo / Kanto", 35.9251, 139.4855),
    ("Nara", "Kyoto - Osaka / Kansai", 34.6851, 135.8048),
    ("Uji", "Kyoto - Osaka / Kansai", 34.8845, 135.7996),
    ("Himeji", "Kyoto - Osaka / Kansai", 34.8154, 134.6853),
    ("Miyajima", "Hiroshima / Chugoku", 34.2969, 132.3197),
    ("Otaru", "Sapporo / Hokkaido", 43.1907, 140.9947),
    ("Dazaifu", "Fukuoka / Kyushu", 33.5147, 130.5350),
]


def seed_if_empty(session: Session) -> None:
    existing = session.exec(select(Location)).first()
    if existing is not None:
        return

    hub_by_name: dict[str, Location] = {}
    for name, lat, lon, map_inset in HUBS:
        hub = Location(name=name, is_hub=True, lat=lat, lon=lon, map_inset=map_inset)
        session.add(hub)
        session.flush()
        hub_by_name[name] = hub

    for name, hub_name, lat, lon in SATELLITES:
        parent = hub_by_name[hub_name]
        session.add(Location(name=name, is_hub=False, parent_id=parent.id, lat=lat, lon=lon))

    session.commit()

from sqlmodel import Session, select

from app.models import Category, Location

HUBS = [
    ("Sapporo / Hokkaido", 43.0621, 141.3544),
    ("Sendai / Tohoku", 38.2682, 140.8694),
    ("Tokyo / Kanto", 35.6762, 139.6503),
    ("Nagoya / Chubu", 35.1815, 136.9066),
    ("Kyoto / Kansai", 35.0116, 135.7681),
    ("Osaka / Kansai", 34.6937, 135.5023),
    ("Hiroshima / Chugoku", 34.3853, 132.4553),
    ("Matsuyama / Shikoku", 33.8392, 132.7657),
    ("Fukuoka / Kyushu", 33.5904, 130.4017),
    ("Okinawa", 26.2124, 127.6809),
]

SATELLITES = [
    ("Nikko", "Tokyo / Kanto", 36.7199, 139.6982),
    ("Kamakura", "Tokyo / Kanto", 35.3193, 139.5466),
    ("Hakone", "Tokyo / Kanto", 35.2323, 139.1069),
    ("Kawagoe", "Tokyo / Kanto", 35.9251, 139.4855),
    ("Nara", "Kyoto / Kansai", 34.6851, 135.8048),
    ("Uji", "Kyoto / Kansai", 34.8845, 135.7996),
    ("Himeji", "Osaka / Kansai", 34.8154, 134.6853),
    ("Miyajima", "Hiroshima / Chugoku", 34.2969, 132.3197),
    ("Otaru", "Sapporo / Hokkaido", 43.1907, 140.9947),
    ("Dazaifu", "Fukuoka / Kyushu", 33.5147, 130.5350),
]

DEFAULT_CATEGORIES = [
    ("food", "Cibo", "🍜", "#A63A2E"),
    ("culture", "Cultura", "⛩️", "#35496B"),
    ("nature", "Natura", "🌸", "#7A8F5E"),
    ("shopping", "Shopping", "🛍️", "#B08D57"),
    ("stay", "Alloggio", "🏨", "#5B4636"),
    ("transport", "Trasporti", "🚄", "#1F2C47"),
    ("experience", "Esperienza", "🎡", "#8E5572"),
]


def seed_if_empty(session: Session) -> None:
    if session.exec(select(Location)).first() is None:
        hub_by_name: dict[str, Location] = {}
        for name, lat, lon in HUBS:
            hub = Location(name=name, is_hub=True, lat=lat, lon=lon)
            session.add(hub)
            session.flush()
            hub_by_name[name] = hub

        for name, hub_name, lat, lon in SATELLITES:
            parent = hub_by_name[hub_name]
            session.add(Location(name=name, is_hub=False, parent_id=parent.id, lat=lat, lon=lon))

        session.commit()

    if session.exec(select(Category)).first() is None:
        for key, label, icon, color in DEFAULT_CATEGORIES:
            session.add(Category(key=key, label=label, icon=icon, color=color))
        session.commit()

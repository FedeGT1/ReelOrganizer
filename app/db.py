import os

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.environ.get("REEL_DB_PATH", "data/japan_reels.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Columns added to tables that already shipped on existing deployments.
# create_all() only creates missing tables, never alters existing ones, so
# any column added to a SQLModel class after its table first shipped needs
# an entry here or it will silently never exist on an upgraded DB.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "location": [("geocode_confidence", "TEXT")],
    "reel": [("caption", "TEXT"), ("transcript", "TEXT")],
}


def _ensure_columns(target_engine: Engine) -> None:
    with target_engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            table_exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {"name": table},
            ).first()
            if not table_exists:
                continue
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, col_type in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))


def create_db_and_tables() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)


def get_session():
    with Session(engine) as session:
        yield session

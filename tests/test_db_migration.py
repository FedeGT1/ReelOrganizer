from sqlalchemy import create_engine, text

from app.db import _ensure_columns


def _make_old_schema_engine(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE reel (id TEXT PRIMARY KEY, link TEXT, location_id TEXT, "
                "note TEXT, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO reel (id, link, location_id, note, created_at) "
                "VALUES ('r1', 'https://instagram.com/reel/x', 'loc1', 'existing note', '2026-01-01')"
            )
        )
    return engine


def test_ensure_columns_adds_missing_columns_without_touching_existing_rows(tmp_path):
    engine = _make_old_schema_engine(tmp_path)

    _ensure_columns(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(reel)"))}
        assert "caption" in columns
        assert "transcript" in columns

        row = conn.execute(text("SELECT link, note FROM reel WHERE id = 'r1'")).first()
        assert row.link == "https://instagram.com/reel/x"
        assert row.note == "existing note"


def test_ensure_columns_is_idempotent(tmp_path):
    engine = _make_old_schema_engine(tmp_path)

    _ensure_columns(engine)
    _ensure_columns(engine)  # must not raise on the second run

    with engine.connect() as conn:
        row = conn.execute(text("SELECT link FROM reel WHERE id = 'r1'")).first()
        assert row.link == "https://instagram.com/reel/x"

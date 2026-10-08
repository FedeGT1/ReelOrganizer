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


from datetime import datetime

from app.db import _get_or_create_bootstrap_user, _migrate_category_table_if_needed, _needs_user_migration


def _make_pre_multiuser_engine(tmp_path):
    db_path = tmp_path / "pre_multiuser.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE user (id TEXT PRIMARY KEY, username TEXT UNIQUE, "
            "password_hash TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE location (id TEXT PRIMARY KEY, name TEXT, is_hub BOOLEAN, "
            "parent_id TEXT, lat REAL, lon REAL, geocode_confidence TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE reel (id TEXT PRIMARY KEY, link TEXT, location_id TEXT, "
            "note TEXT, caption TEXT, transcript TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE aisession (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE asksession (id TEXT PRIMARY KEY, location_id TEXT, "
            "category_key TEXT, created_at TEXT, updated_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE category (key TEXT PRIMARY KEY, label TEXT, icon TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO location (id, name, is_hub) VALUES ('loc1', 'Tokyo', 1)"
        ))
        conn.execute(text(
            "INSERT INTO reel (id, link, location_id, created_at) "
            "VALUES ('r1', 'https://instagram.com/reel/x', 'loc1', '2026-01-01')"
        ))
        conn.execute(text(
            "INSERT INTO category (key, label, icon, created_at) "
            "VALUES ('food', 'Cibo', '🍜', '2026-01-01')"
        ))
    return engine


def test_needs_user_migration_true_for_pre_multiuser_db(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")
    # location/reel/asksession don't have user_id yet -- add it as _ensure_columns would
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE location ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE reel ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE aisession ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE asksession ADD COLUMN user_id TEXT"))

    with engine.connect() as conn:
        assert _needs_user_migration(conn) is True


def test_get_or_create_bootstrap_user_creates_one_from_env_vars(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        user_id = _get_or_create_bootstrap_user(conn)
        row = conn.execute(text("SELECT username FROM user WHERE id = :id"), {"id": user_id}).first()
        assert row.username == "owner"


def test_get_or_create_bootstrap_user_is_idempotent(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        first_id = _get_or_create_bootstrap_user(conn)
        second_id = _get_or_create_bootstrap_user(conn)
        assert first_id == second_id
        count = conn.execute(text("SELECT COUNT(*) FROM user")).scalar()
        assert count == 1


def test_migrate_category_table_rebuilds_with_composite_key(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        bootstrap_id = _get_or_create_bootstrap_user(conn)
        _migrate_category_table_if_needed(conn, bootstrap_id)

        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(category)"))}
        assert "user_id" in columns
        row = conn.execute(
            text("SELECT user_id, label FROM category WHERE key = 'food'")
        ).first()
        assert row.user_id == bootstrap_id
        assert row.label == "Cibo"


def test_migrate_category_table_is_idempotent(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        bootstrap_id = _get_or_create_bootstrap_user(conn)
        _migrate_category_table_if_needed(conn, bootstrap_id)
        _migrate_category_table_if_needed(conn, bootstrap_id)  # must not raise

        count = conn.execute(text("SELECT COUNT(*) FROM category")).scalar()
        assert count == 1

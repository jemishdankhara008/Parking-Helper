# ============================================
# SECTION: SQLite store — reservations + users
# ============================================

"""SQLite helpers for the shared reservations/users store used by the API and tests."""

import sqlite3
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
_db_path_raw = os.environ.get("PARKING_HELPER_DB_PATH", str(DATA / "reservations.db"))
DB_PATH = _db_path_raw if _db_path_raw.startswith("file:") else Path(_db_path_raw).expanduser()


def get_db():
    if isinstance(DB_PATH, Path):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
    else:
        conn = sqlite3.connect(DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        # The schema is kept intentionally lightweight so both tests and Streamlit clients can work through the API.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_id TEXT NOT NULL,
                lot_id TEXT NOT NULL,
                reserved_by TEXT NOT NULL,
                reserved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                status TEXT DEFAULT 'active'
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.commit()
        _migrate_users_profile_columns(conn)
    finally:
        conn.close()


def _migrate_users_profile_columns(conn):
    for col in ("full_name", "phone"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass


init_db()

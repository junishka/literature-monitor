"""Database models for the Literature Monitor web app.

Supports both SQLite (local dev) and PostgreSQL (production/Render).
Detects which to use via the DATABASE_URL environment variable.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

# If DATABASE_URL is set, use PostgreSQL; otherwise SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Render uses "postgres://" but psycopg2 needs "postgresql://"
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLITE_PATH = Path(__file__).parent.parent / "litmonitor.db"


@contextmanager
def get_db():
    """Get a database connection. Works with both SQLite and PostgreSQL."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(str(SQLITE_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _fetchone(conn, query, params=()):
    cur = conn.cursor()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    row = cur.fetchone()
    if row and not USE_POSTGRES:
        return dict(row)
    return dict(row) if row else None


def _fetchall(conn, query, params=()):
    cur = conn.cursor()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    rows = cur.fetchall()
    if not USE_POSTGRES:
        return [dict(r) for r in rows]
    return [dict(r) for r in rows]


def _execute(conn, query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    return cur


# Use %s for postgres, ? for sqlite
def _ph(count=1):
    """Return placeholder(s) for the current DB engine."""
    p = "%s" if USE_POSTGRES else "?"
    return ", ".join([p] * count)


def init_db():
    """Create all tables if they don't exist."""
    # Adapt SQL syntax for each DB
    if USE_POSTGRES:
        serial = "SERIAL PRIMARY KEY"
        upsert_settings = "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    else:
        serial = "INTEGER PRIMARY KEY AUTOINCREMENT"
        upsert_settings = None  # handled differently

    with get_db() as conn:
        cur = conn.cursor()

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {serial},
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS searches (
                id {serial},
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS search_journals (
                id {serial},
                search_id INTEGER NOT NULL,
                journal_openalex_id TEXT NOT NULL,
                journal_name TEXT NOT NULL
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS digests (
                id {serial},
                user_id INTEGER NOT NULL,
                run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_papers INTEGER DEFAULT 0,
                html_content TEXT,
                sent_email INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_papers (
                paper_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT,
                doi TEXT,
                pub_date TEXT DEFAULT '',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (paper_id, user_id)
            )
        """)

        # Migration: add pub_date column if missing
        try:
            cur.execute("ALTER TABLE seen_papers ADD COLUMN pub_date TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                value TEXT,
                PRIMARY KEY (key, user_id)
            )
        """)

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS journal_sets (
                id {serial},
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                journals TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# --- Users ---

def create_user(email: str, password_hash: str, name: str = "") -> int:
    with get_db() as conn:
        if USE_POSTGRES:
            cur = _execute(conn, "INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id", (email, password_hash, name))
            return cur.fetchone()[0]
        else:
            cur = _execute(conn, "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)", (email, password_hash, name))
            return cur.lastrowid


def get_user_by_email(email: str) -> dict | None:
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM users WHERE email = {_ph()}", (email,))


def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM users WHERE id = {_ph()}", (user_id,))


# --- Search CRUD (per user) ---

def create_search(user_id: int, name: str, keywords: list[str]) -> int:
    with get_db() as conn:
        if USE_POSTGRES:
            cur = _execute(conn, "INSERT INTO searches (user_id, name, keywords) VALUES (%s, %s, %s) RETURNING id", (user_id, name, json.dumps(keywords)))
            return cur.fetchone()[0]
        else:
            cur = _execute(conn, "INSERT INTO searches (user_id, name, keywords) VALUES (?, ?, ?)", (user_id, name, json.dumps(keywords)))
            return cur.lastrowid


def get_search(search_id: int, user_id: int) -> dict | None:
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT * FROM searches WHERE id = {_ph()} AND user_id = {_ph()}", (search_id, user_id))
        if row:
            row["keywords"] = json.loads(row["keywords"])
        return row


def get_all_searches(user_id: int) -> list[dict]:
    with get_db() as conn:
        rows = _fetchall(conn, f"SELECT * FROM searches WHERE user_id = {_ph()} ORDER BY created_at DESC", (user_id,))
        for r in rows:
            r["keywords"] = json.loads(r["keywords"])
        return rows


def update_search(search_id: int, user_id: int, name: str, keywords: list[str]):
    with get_db() as conn:
        _execute(conn, f"UPDATE searches SET name = {_ph()}, keywords = {_ph()} WHERE id = {_ph()} AND user_id = {_ph()}",
                 (name, json.dumps(keywords), search_id, user_id))


def delete_search(search_id: int, user_id: int):
    with get_db() as conn:
        _execute(conn, f"DELETE FROM search_journals WHERE search_id = {_ph()}", (search_id,))
        _execute(conn, f"DELETE FROM searches WHERE id = {_ph()} AND user_id = {_ph()}", (search_id, user_id))


# --- Search Journals ---

def set_search_journals(search_id: int, journals: list[dict]):
    with get_db() as conn:
        _execute(conn, f"DELETE FROM search_journals WHERE search_id = {_ph()}", (search_id,))
        for j in journals:
            _execute(conn, f"INSERT INTO search_journals (search_id, journal_openalex_id, journal_name) VALUES ({_ph(3)})",
                     (search_id, j["id"], j["name"]))


def get_search_journals(search_id: int) -> list[dict]:
    with get_db() as conn:
        return _fetchall(conn, f"SELECT journal_openalex_id as id, journal_name as name FROM search_journals WHERE search_id = {_ph()}", (search_id,))


# --- Digests (per user) ---

def save_digest(user_id: int, total_papers: int, html_content: str, sent_email: bool = False) -> int:
    with get_db() as conn:
        if USE_POSTGRES:
            cur = _execute(conn, "INSERT INTO digests (user_id, total_papers, html_content, sent_email) VALUES (%s, %s, %s, %s) RETURNING id",
                           (user_id, total_papers, html_content, int(sent_email)))
            return cur.fetchone()[0]
        else:
            cur = _execute(conn, "INSERT INTO digests (user_id, total_papers, html_content, sent_email) VALUES (?, ?, ?, ?)",
                           (user_id, total_papers, html_content, int(sent_email)))
            return cur.lastrowid


def get_digest(digest_id: int, user_id: int) -> dict | None:
    with get_db() as conn:
        return _fetchone(conn, f"SELECT * FROM digests WHERE id = {_ph()} AND user_id = {_ph()}", (digest_id, user_id))


def get_recent_digests(user_id: int, limit: int = 20) -> list[dict]:
    with get_db() as conn:
        return _fetchall(conn, f"SELECT id, run_date, total_papers, sent_email FROM digests WHERE user_id = {_ph()} ORDER BY run_date DESC LIMIT {_ph()}",
                         (user_id, limit))


# --- Settings (per user) ---

def get_setting(user_id: int, key: str, default: str = "") -> str:
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT value FROM settings WHERE key = {_ph()} AND user_id = {_ph()}", (key, user_id))
        return row["value"] if row else default


def set_setting(user_id: int, key: str, value: str):
    with get_db() as conn:
        if USE_POSTGRES:
            _execute(conn, "INSERT INTO settings (key, user_id, value) VALUES (%s, %s, %s) ON CONFLICT (key, user_id) DO UPDATE SET value = EXCLUDED.value",
                     (key, user_id, value))
        else:
            _execute(conn, "INSERT OR REPLACE INTO settings (key, user_id, value) VALUES (?, ?, ?)",
                     (key, user_id, value))


def get_all_settings(user_id: int) -> dict:
    with get_db() as conn:
        rows = _fetchall(conn, f"SELECT key, value FROM settings WHERE user_id = {_ph()}", (user_id,))
        return {r["key"]: r["value"] for r in rows}


# --- Journal Sets (per user) ---

def save_journal_set(user_id: int, name: str, journals: list[dict]) -> int:
    """Save a reusable set of journals. journals = [{"id": "S...", "name": "..."}]"""
    with get_db() as conn:
        if USE_POSTGRES:
            cur = _execute(conn, "INSERT INTO journal_sets (user_id, name, journals) VALUES (%s, %s, %s) RETURNING id",
                           (user_id, name, json.dumps(journals)))
            return cur.fetchone()[0]
        else:
            cur = _execute(conn, "INSERT INTO journal_sets (user_id, name, journals) VALUES (?, ?, ?)",
                           (user_id, name, json.dumps(journals)))
            return cur.lastrowid


def get_journal_sets(user_id: int) -> list[dict]:
    with get_db() as conn:
        rows = _fetchall(conn, f"SELECT * FROM journal_sets WHERE user_id = {_ph()} ORDER BY name", (user_id,))
        for r in rows:
            r["journals"] = json.loads(r["journals"])
        return rows


def get_journal_set(set_id: int, user_id: int) -> dict | None:
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT * FROM journal_sets WHERE id = {_ph()} AND user_id = {_ph()}", (set_id, user_id))
        if row:
            row["journals"] = json.loads(row["journals"])
        return row


def delete_journal_set(set_id: int, user_id: int):
    with get_db() as conn:
        _execute(conn, f"DELETE FROM journal_sets WHERE id = {_ph()} AND user_id = {_ph()}", (set_id, user_id))


# --- Seen Papers (per user) ---

def get_seen_count(user_id: int) -> int:
    with get_db() as conn:
        row = _fetchone(conn, f"SELECT COUNT(*) as cnt FROM seen_papers WHERE user_id = {_ph()}", (user_id,))
        return row["cnt"] if row else 0


def get_seen_papers(user_id: int, limit: int = 500, sort: str = "first_seen", order: str = "desc") -> list[dict]:
    allowed_sorts = {"first_seen": "first_seen", "pub_date": "pub_date"}
    sort_col = allowed_sorts.get(sort, "first_seen")
    order_dir = "ASC" if order == "asc" else "DESC"
    with get_db() as conn:
        return _fetchall(conn,
            f"SELECT paper_id, title, doi, pub_date, first_seen FROM seen_papers WHERE user_id = {_ph()} ORDER BY {sort_col} {order_dir} LIMIT {_ph()}",
            (user_id, limit))


def reset_seen_papers(user_id: int):
    with get_db() as conn:
        _execute(conn, f"DELETE FROM seen_papers WHERE user_id = {_ph()}", (user_id,))

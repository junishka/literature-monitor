"""SQLite database models for the Literature Monitor web app."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "litmonitor.db"


def get_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DB_PATH):
    """Create all tables if they don't exist."""
    conn = get_db(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            keywords TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS search_journals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            journal_openalex_id TEXT NOT NULL,
            journal_name TEXT NOT NULL,
            FOREIGN KEY (search_id) REFERENCES searches(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT DEFAULT (datetime('now')),
            total_papers INTEGER DEFAULT 0,
            html_content TEXT,
            sent_email INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS seen_papers (
            paper_id TEXT PRIMARY KEY,
            title TEXT,
            doi TEXT,
            first_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


# --- Search CRUD ---

def create_search(name: str, keywords: list[str]) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO searches (name, keywords) VALUES (?, ?)",
        (name, json.dumps(keywords)),
    )
    conn.commit()
    search_id = cur.lastrowid
    conn.close()
    return search_id


def get_search(search_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["keywords"] = json.loads(d["keywords"])
        return d
    return None


def get_all_searches() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM searches ORDER BY created_at DESC").fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["keywords"] = json.loads(d["keywords"])
        results.append(d)
    return results


def update_search(search_id: int, name: str, keywords: list[str]):
    conn = get_db()
    conn.execute(
        "UPDATE searches SET name = ?, keywords = ? WHERE id = ?",
        (name, json.dumps(keywords), search_id),
    )
    conn.commit()
    conn.close()


def delete_search(search_id: int):
    conn = get_db()
    conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
    conn.commit()
    conn.close()


# --- Search Journals ---

def set_search_journals(search_id: int, journals: list[dict]):
    """Replace all journals for a search. journals = [{"id": "S...", "name": "..."}]"""
    conn = get_db()
    conn.execute("DELETE FROM search_journals WHERE search_id = ?", (search_id,))
    for j in journals:
        conn.execute(
            "INSERT INTO search_journals (search_id, journal_openalex_id, journal_name) VALUES (?, ?, ?)",
            (search_id, j["id"], j["name"]),
        )
    conn.commit()
    conn.close()


def get_search_journals(search_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT journal_openalex_id as id, journal_name as name FROM search_journals WHERE search_id = ?",
        (search_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_journals() -> list[dict]:
    """Get all unique journals across all searches."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT journal_openalex_id as id, journal_name as name FROM search_journals ORDER BY journal_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Digests ---

def save_digest(total_papers: int, html_content: str, sent_email: bool = False) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO digests (total_papers, html_content, sent_email) VALUES (?, ?, ?)",
        (total_papers, html_content, int(sent_email)),
    )
    conn.commit()
    digest_id = cur.lastrowid
    conn.close()
    return digest_id


def get_digest(digest_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM digests WHERE id = ?", (digest_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_digests(limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, run_date, total_papers, sent_email FROM digests ORDER BY run_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Settings ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    conn.commit()
    conn.close()


def get_all_settings() -> dict:
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# --- Seen Papers (dedup) ---

def get_seen_count() -> int:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM seen_papers").fetchone()
    conn.close()
    return row["cnt"]


def reset_seen_papers():
    conn = get_db()
    conn.execute("DELETE FROM seen_papers")
    conn.commit()
    conn.close()

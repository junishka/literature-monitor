"""Track seen papers in SQLite to avoid sending duplicates."""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from .scopus_client import Paper

DEFAULT_DB_PATH = Path(__file__).parent.parent / "litmonitor.db"


class Deduplicator:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT,
                doi TEXT,
                first_seen TEXT
            )
        """)
        self.conn.commit()

    @staticmethod
    def _paper_id(paper: Paper) -> str:
        """Generate a unique ID from DOI or title hash."""
        if paper.doi:
            return f"doi:{paper.doi.lower()}"
        title_hash = hashlib.sha256(paper.title.lower().encode()).hexdigest()[:16]
        return f"title:{title_hash}"

    def filter_new(self, papers: list[Paper]) -> list[Paper]:
        """Return only papers not previously seen."""
        new_papers = []
        for paper in papers:
            pid = self._paper_id(paper)
            cursor = self.conn.execute(
                "SELECT 1 FROM seen_papers WHERE paper_id = ?", (pid,)
            )
            if cursor.fetchone() is None:
                new_papers.append(paper)
        return new_papers

    def mark_seen(self, papers: list[Paper]):
        """Record papers as seen."""
        now = datetime.now().isoformat()
        for paper in papers:
            pid = self._paper_id(paper)
            self.conn.execute(
                "INSERT OR IGNORE INTO seen_papers (paper_id, title, doi, first_seen) VALUES (?, ?, ?, ?)",
                (pid, paper.title, paper.doi, now),
            )
        self.conn.commit()

    def close(self):
        self.conn.close()

"""Track seen papers to avoid sending duplicates. Uses the shared DB from models."""

import hashlib
from datetime import datetime

from . import models
from .scopus_client import Paper


class Deduplicator:
    def __init__(self, user_id: int):
        self.user_id = user_id

    @staticmethod
    def _paper_id(paper: Paper) -> str:
        """Generate a unique ID from DOI or title hash."""
        if paper.doi:
            return f"doi:{paper.doi.lower()}"
        title_hash = hashlib.sha256(paper.title.lower().encode()).hexdigest()[:16]
        return f"title:{title_hash}"

    def filter_new(self, papers: list[Paper]) -> list[Paper]:
        """Return only papers not previously seen by this user."""
        new_papers = []
        ph = models._ph()
        with models.get_db() as conn:
            for paper in papers:
                pid = self._paper_id(paper)
                row = models._fetchone(
                    conn,
                    f"SELECT 1 FROM seen_papers WHERE paper_id = {ph} AND user_id = {ph}",
                    (pid, self.user_id),
                )
                if row is None:
                    new_papers.append(paper)
        return new_papers

    def mark_seen(self, papers: list[Paper]):
        """Record papers as seen for this user."""
        now = datetime.now().isoformat()
        with models.get_db() as conn:
            for paper in papers:
                pid = self._paper_id(paper)
                try:
                    models._execute(
                        conn,
                        f"INSERT INTO seen_papers (paper_id, user_id, title, doi, pub_date, first_seen) VALUES ({models._ph(6)})",
                        (pid, self.user_id, paper.title, paper.doi, paper.date, now),
                    )
                except Exception:
                    pass  # Already exists, skip

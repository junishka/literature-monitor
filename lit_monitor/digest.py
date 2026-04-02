"""Build the HTML email digest from search results."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import os

from jinja2 import Environment, FileSystemLoader

from .scopus_client import Paper

# Use absolute path based on project root, not relative to this file
_PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent
TEMPLATE_DIR = _PROJECT_ROOT / "templates" / "email"


@dataclass
class TopicResults:
    name: str
    papers: list[Paper]


def build_digest(topics: list[TopicResults], run_date: date | None = None) -> str:
    """Render the digest HTML from topic results."""
    if run_date is None:
        run_date = date.today()

    total_papers = sum(len(t.papers) for t in topics)

    # Try multiple possible template locations
    possible_dirs = [
        TEMPLATE_DIR,
        Path(__file__).parent.parent / "templates" / "email",
        Path(__file__).parent / "templates",
    ]

    template_dir = None
    for d in possible_dirs:
        if (d / "digest.html").exists():
            template_dir = d
            break

    if not template_dir:
        raise FileNotFoundError(
            f"digest.html not found. Searched: {[str(d) for d in possible_dirs]}"
        )

    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("digest.html")

    return template.render(
        topics=topics,
        total_papers=total_papers,
        run_date=run_date.strftime("%B %d, %Y"),
    )

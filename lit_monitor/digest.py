"""Build the HTML email digest from search results."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .scopus_client import Paper

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class TopicResults:
    name: str
    papers: list[Paper]


def build_digest(topics: list[TopicResults], run_date: date | None = None) -> str:
    """Render the digest HTML from topic results."""
    if run_date is None:
        run_date = date.today()

    total_papers = sum(len(t.papers) for t in topics)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("digest.html")

    return template.render(
        topics=topics,
        total_papers=total_papers,
        run_date=run_date.strftime("%B %d, %Y"),
    )

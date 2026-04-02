"""Main orchestrator — search OpenAlex, deduplicate, build digest, send email."""

import logging
from datetime import date, timedelta
from pathlib import Path

from .config import AppConfig, load_config
from .dedup import Deduplicator
from .digest import TopicResults, build_digest
from .emailer import send_digest
from .openalex_client import search_openalex
from .scopus_client import Paper

logger = logging.getLogger(__name__)


def get_since_date(dedup: Deduplicator, lookback_days: int) -> date:
    """Determine the start date for searches."""
    cursor = dedup.conn.execute("SELECT COUNT(*) FROM seen_papers")
    count = cursor.fetchone()[0]
    if count > 0:
        return date.today() - timedelta(days=7)
    return date.today() - timedelta(days=lookback_days)


def run(config_path: str = "config.yaml", dry_run: bool = False, output_html: str | None = None):
    """Main entry point: query OpenAlex, deduplicate, digest, send."""
    config = load_config(config_path)
    dedup = Deduplicator()

    since_date = get_since_date(dedup, config.initial_lookback_days)
    logger.info(f"Searching for papers published since {since_date}")

    # Get journal source IDs
    source_ids = [j.id for j in config.journals] if config.journals else None

    all_topics: list[TopicResults] = []
    all_new_papers: list[Paper] = []

    for search in config.searches:
        logger.info(f"Running search: {search.name}")

        papers = search_openalex(
            keywords=search.keywords,
            since_date=since_date,
            source_ids=source_ids,
        )

        new_papers = dedup.filter_new(papers)
        logger.info(f"  {search.name}: {len(papers)} found, {len(new_papers)} new")

        all_topics.append(TopicResults(name=search.name, papers=new_papers))
        all_new_papers.extend(new_papers)

    # Build digest
    html = build_digest(all_topics)

    total = len(all_new_papers)
    logger.info(f"Total new papers: {total}")

    # Save HTML locally if requested
    if output_html:
        Path(output_html).write_text(html)
        logger.info(f"Digest saved to {output_html}")

    # Always save a local copy of the digest
    if not output_html:
        output_html = f"digest_{date.today().isoformat()}.html"
    Path(output_html).write_text(html)
    logger.info(f"Digest saved to {output_html}")

    if dry_run:
        print(f"\n[DRY RUN] Would send digest with {total} new papers.")
    elif total > 0:
        subject = f"Literature Digest — {total} new paper{'s' if total != 1 else ''} ({date.today().strftime('%b %d')})"
        try:
            send_digest(config.email, subject, html)
        except Exception as e:
            logger.error(f"Email failed: {e}")
            print(f"\nEmail failed, but digest saved to {output_html}")
    else:
        logger.info("No new papers found, skipping email")

    # Mark all new papers as seen
    dedup.mark_seen(all_new_papers)
    dedup.close()

    return total

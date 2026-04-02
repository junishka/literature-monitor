"""Background scheduler for periodic literature searches."""

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from . import models
from .dedup import Deduplicator
from .digest import TopicResults, build_digest
from .emailer import send_digest
from .config import EmailConfig
from .openalex_client import search_openalex
from .scopus_client import Paper

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_searches_for_user(user_id: int) -> int:
    """Run all searches for a specific user."""
    searches = models.get_all_searches(user_id)
    if not searches:
        return 0

    settings = models.get_all_settings(user_id)
    mailto = settings.get("email_sender", "")
    lookback = int(settings.get("lookback_days", "30"))

    # Determine date range
    seen_count = models.get_seen_count(user_id)
    if seen_count > 0:
        since_date = date.today() - timedelta(days=7)
    else:
        since_date = date.today() - timedelta(days=lookback)

    dedup = Deduplicator(user_id)
    all_topics: list[TopicResults] = []
    all_new_papers: list[Paper] = []

    for search in searches:
        journals = models.get_search_journals(search["id"])
        source_ids = [j["id"] for j in journals] if journals else None

        papers = search_openalex(
            keywords=search["keywords"],
            since_date=since_date,
            source_ids=source_ids,
            mailto=mailto,
        )

        new_papers = dedup.filter_new(papers)
        logger.info(f"  {search['name']}: {len(papers)} found, {len(new_papers)} new")

        all_topics.append(TopicResults(name=search["name"], papers=new_papers))
        all_new_papers.extend(new_papers)

    html = build_digest(all_topics)
    total = len(all_new_papers)

    # Try to send email
    sent = False
    if total > 0:
        sender = settings.get("email_sender", "")
        password = settings.get("email_password", "")
        recipients_str = settings.get("email_recipients", "")
        recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

        if sender and password and recipients:
            email_config = EmailConfig(
                smtp_host=settings.get("smtp_host", "smtp.gmail.com"),
                smtp_port=int(settings.get("smtp_port", "587")),
                use_tls=True,
                sender=sender,
                password=password,
                recipients=recipients,
            )
            subject = f"Literature Digest — {total} new paper{'s' if total != 1 else ''} ({date.today().strftime('%b %d')})"
            try:
                send_digest(email_config, subject, html)
                sent = True
            except Exception as e:
                logger.error(f"Email send failed for user {user_id}: {e}")

    models.save_digest(user_id, total, html, sent)
    dedup.mark_seen(all_new_papers)

    logger.info(f"User {user_id}: {total} new papers, email sent: {sent}")
    return total


def run_all_users():
    """Run searches for all users (called by scheduler)."""
    logger.info("Scheduler: running searches for all users")
    with models.get_db() as conn:
        users = models._fetchall(conn, "SELECT id FROM users")

    for user in users:
        try:
            run_searches_for_user(user["id"])
        except Exception as e:
            logger.error(f"Scheduler error for user {user['id']}: {e}")


def start_scheduler():
    """Start the background scheduler."""
    if scheduler.get_job("lit_monitor_job"):
        scheduler.remove_job("lit_monitor_job")

    # Run weekly on Mondays at 9am (default)
    scheduler.add_job(run_all_users, "cron", day_of_week="mon", hour=9, id="lit_monitor_job")

    if not scheduler.running:
        scheduler.start()

    logger.info("Scheduler started: weekly on Mondays at 9am")


def get_next_run():
    """Get the next scheduled run time."""
    job = scheduler.get_job("lit_monitor_job")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M")
    return None

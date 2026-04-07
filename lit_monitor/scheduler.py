"""Background scheduler for periodic literature searches."""

import logging
import os
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

# Read Gmail credentials at import time (threads may not see env vars reliably)
GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


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

    # Try to send email using central Gmail account
    sent = False
    if total > 0:
        sender = os.environ.get("GMAIL_SENDER", "") or GMAIL_SENDER
        password = os.environ.get("GMAIL_APP_PASSWORD", "") or GMAIL_PASSWORD
        recipients_str = settings.get("email_recipients", "")
        recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

        logger.info(f"Email config: sender={'yes' if sender else 'NO'}, password={'yes' if password else 'NO'}, recipients={recipients}")
        if sender and password and recipients:
            email_config = EmailConfig(
                smtp_host="smtp.gmail.com",
                smtp_port=587,
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

    # Only save digest if papers were found
    if total > 0:
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


def start_scheduler(frequency="weekly", day="monday", hour=9):
    """Start or restart the background scheduler with given settings."""
    if scheduler.get_job("lit_monitor_job"):
        scheduler.remove_job("lit_monitor_job")

    day_short = day[:3].lower()
    hour = int(hour)

    if frequency == "daily":
        scheduler.add_job(run_all_users, "cron", hour=hour, minute=0, id="lit_monitor_job",
                          replace_existing=True)
        desc = f"daily at {hour}:00"
    elif frequency == "biweekly":
        # Use cron on the chosen day/hour, skip even weeks
        scheduler.add_job(run_all_users, "cron", day_of_week=day_short, hour=hour, minute=0,
                          week="1-53/2", id="lit_monitor_job", replace_existing=True)
        desc = f"every 2 weeks on {day}s at {hour}:00"
    elif frequency == "monthly":
        scheduler.add_job(run_all_users, "cron", day=1, hour=hour, minute=0, id="lit_monitor_job",
                          replace_existing=True)
        desc = f"monthly on the 1st at {hour}:00"
    else:  # weekly
        scheduler.add_job(run_all_users, "cron", day_of_week=day_short, hour=hour, minute=0,
                          id="lit_monitor_job", replace_existing=True)
        desc = f"weekly on {day}s at {hour}:00"

    if not scheduler.running:
        scheduler.start()

    logger.info(f"Scheduler started: {desc}")


def get_next_run():
    """Get the next scheduled run time."""
    job = scheduler.get_job("lit_monitor_job")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M")
    return None

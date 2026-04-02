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


def run_all_searches() -> int:
    """Run all configured searches, build digest, send email."""
    logger.info("Scheduler: starting search run")

    searches = models.get_all_searches()
    if not searches:
        logger.info("No searches configured, skipping")
        return 0

    settings = models.get_all_settings()
    mailto = settings.get("email_sender", "")
    lookback = int(settings.get("lookback_days", "30"))

    # Determine date range
    seen_count = models.get_seen_count()
    if seen_count > 0:
        since_date = date.today() - timedelta(days=7)
    else:
        since_date = date.today() - timedelta(days=lookback)

    dedup = Deduplicator(models.DB_PATH)
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

    # Build digest
    html = build_digest(all_topics)
    total = len(all_new_papers)

    # Save digest to DB
    sent = False
    if total > 0:
        # Try to send email
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
                logger.error(f"Email send failed: {e}")

    models.save_digest(total, html, sent)
    dedup.mark_seen(all_new_papers)
    dedup.close()

    logger.info(f"Scheduler: done — {total} new papers, email sent: {sent}")
    return total


def start_scheduler():
    """Start the background scheduler based on saved settings."""
    settings = models.get_all_settings()
    frequency = settings.get("schedule_frequency", "weekly")
    day = settings.get("schedule_day", "monday")
    hour = int(settings.get("schedule_hour", "9"))

    # Remove existing job if any
    if scheduler.get_job("lit_monitor_job"):
        scheduler.remove_job("lit_monitor_job")

    if frequency == "daily":
        scheduler.add_job(run_all_searches, "cron", hour=hour, id="lit_monitor_job")
    elif frequency == "weekly":
        scheduler.add_job(run_all_searches, "cron", day_of_week=day[:3].lower(), hour=hour, id="lit_monitor_job")
    elif frequency == "biweekly":
        scheduler.add_job(run_all_searches, "interval", weeks=2, id="lit_monitor_job")
    elif frequency == "monthly":
        scheduler.add_job(run_all_searches, "cron", day=1, hour=hour, id="lit_monitor_job")

    if not scheduler.running:
        scheduler.start()

    logger.info(f"Scheduler started: {frequency} (day={day}, hour={hour})")


def get_next_run():
    """Get the next scheduled run time."""
    job = scheduler.get_job("lit_monitor_job")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M")
    return None

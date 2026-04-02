"""Literature Monitor — Flask web application with user auth."""

import logging
import os
from datetime import date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash

from lit_monitor import models
from lit_monitor.journal_lookup import search_journals, get_top_journals_for_field
from lit_monitor.scheduler import run_searches_for_user, start_scheduler, get_next_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lit-monitor-dev-key-change-in-production")


# --- Auth helpers ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def load_user():
    models.init_db()
    g.user = None
    if "user_id" in session:
        g.user = models.get_user_by_id(session["user_id"])
        if not g.user:
            session.pop("user_id", None)


# --- Auth routes ---

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")

        existing = models.get_user_by_email(email)
        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        pw_hash = generate_password_hash(password)
        user_id = models.create_user(email, pw_hash, name)

        # Set defaults
        models.set_setting(user_id, "smtp_host", "smtp.gmail.com")
        models.set_setting(user_id, "smtp_port", "587")
        models.set_setting(user_id, "schedule_frequency", "weekly")
        models.set_setting(user_id, "schedule_day", "monday")
        models.set_setting(user_id, "schedule_hour", "9")
        models.set_setting(user_id, "lookback_days", "90")

        session["user_id"] = user_id
        flash(f"Welcome, {name or email}!", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = models.get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name'] or email}!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# --- Dashboard ---

@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    searches = models.get_all_searches(user_id)
    for s in searches:
        s["journals"] = models.get_search_journals(s["id"])

    digests = models.get_recent_digests(user_id, 10)
    next_run = get_next_run()
    seen_count = models.get_seen_count(user_id)

    return render_template(
        "index.html",
        searches=searches,
        digests=digests,
        next_run=next_run,
        seen_count=seen_count,
    )


# --- Searches ---

@app.route("/searches/new", methods=["GET", "POST"])
@login_required
def new_search():
    user_id = session["user_id"]
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        keywords_raw = request.form.get("keywords", "")
        keywords = [k.strip() for k in keywords_raw.split("\n") if k.strip()]

        if not name or not keywords:
            flash("Please provide a name and at least one keyword.", "error")
            return render_template("search_form.html", search=None, journals=[])

        search_id = models.create_search(user_id, name, keywords)

        journal_ids = request.form.getlist("journal_ids")
        journal_names = request.form.getlist("journal_names")
        journals = [{"id": jid, "name": jname} for jid, jname in zip(journal_ids, journal_names)]
        if journals:
            models.set_search_journals(search_id, journals)

        flash(f"Search '{name}' created!", "success")
        return redirect(url_for("index"))

    return render_template("search_form.html", search=None, journals=[])


@app.route("/searches/<int:search_id>/edit", methods=["GET", "POST"])
@login_required
def edit_search(search_id):
    user_id = session["user_id"]
    search = models.get_search(search_id, user_id)
    if not search:
        flash("Search not found.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        keywords_raw = request.form.get("keywords", "")
        keywords = [k.strip() for k in keywords_raw.split("\n") if k.strip()]

        if not name or not keywords:
            flash("Please provide a name and at least one keyword.", "error")
            return render_template("search_form.html", search=search, journals=models.get_search_journals(search_id))

        models.update_search(search_id, user_id, name, keywords)

        journal_ids = request.form.getlist("journal_ids")
        journal_names = request.form.getlist("journal_names")
        journals = [{"id": jid, "name": jname} for jid, jname in zip(journal_ids, journal_names)]
        models.set_search_journals(search_id, journals)

        flash(f"Search '{name}' updated!", "success")
        return redirect(url_for("index"))

    journals = models.get_search_journals(search_id)
    return render_template("search_form.html", search=search, journals=journals)


@app.route("/searches/<int:search_id>/delete", methods=["POST"])
@login_required
def delete_search(search_id):
    models.delete_search(search_id, session["user_id"])
    flash("Search deleted.", "success")
    return redirect(url_for("index"))


# --- Journals ---

@app.route("/journals")
@login_required
def journals():
    return render_template("journals.html", results=None, query="")


@app.route("/journals/search")
@login_required
def journal_search():
    query = request.args.get("q", "").strip()
    mode = request.args.get("mode", "name")

    if not query:
        return render_template("journals.html", results=None, query="")

    mailto = models.get_setting(session["user_id"], "email_sender", "")

    if mode == "field":
        results = get_top_journals_for_field(query, mailto)
    else:
        results = search_journals(query, mailto)

    return render_template("journals.html", results=results, query=query, mode=mode)


@app.route("/api/journals/search")
@login_required
def api_journal_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    mailto = models.get_setting(session["user_id"], "email_sender", "")
    results = search_journals(query, mailto, max_results=10)
    return jsonify(results)


# --- Settings ---

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = session["user_id"]
    if request.method == "POST":
        fields = [
            "email_sender", "email_password", "email_recipients",
            "smtp_host", "smtp_port",
            "schedule_frequency", "schedule_day", "schedule_hour",
            "lookback_days",
        ]
        for field in fields:
            value = request.form.get(field, "")
            if value:
                models.set_setting(user_id, field, value)
            elif field != "email_password":
                models.set_setting(user_id, field, value)

        flash("Settings saved!", "success")
        return redirect(url_for("settings"))

    current = models.get_all_settings(user_id)
    if current.get("email_password"):
        current["email_password_masked"] = "••••••••"
    else:
        current["email_password_masked"] = ""

    return render_template("settings.html", settings=current)


@app.route("/settings/test-email", methods=["POST"])
@login_required
def test_email():
    from lit_monitor.emailer import send_digest
    from lit_monitor.config import EmailConfig

    user_id = session["user_id"]
    s = models.get_all_settings(user_id)
    sender = s.get("email_sender", "")
    password = s.get("email_password", "")
    recipients = [r.strip() for r in s.get("email_recipients", "").split(",") if r.strip()]

    if not sender or not password or not recipients:
        flash("Please configure email settings first.", "error")
        return redirect(url_for("settings"))

    email_config = EmailConfig(
        smtp_host=s.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(s.get("smtp_port", "587")),
        use_tls=True,
        sender=sender,
        password=password,
        recipients=recipients,
    )

    try:
        send_digest(email_config, "Literature Monitor — Test Email", """
            <html><body>
            <h1>Test Email</h1>
            <p>If you're reading this, your Literature Monitor email is working correctly!</p>
            </body></html>
        """)
        flash("Test email sent!", "success")
    except Exception as e:
        flash(f"Email failed: {e}", "error")

    return redirect(url_for("settings"))


@app.route("/settings/reset-history", methods=["POST"])
@login_required
def reset_history():
    models.reset_seen_papers(session["user_id"])
    flash("Paper history reset. Next run will find all papers as new.", "success")
    return redirect(url_for("settings"))


# --- Digests ---

@app.route("/digests")
@login_required
def digests():
    all_digests = models.get_recent_digests(session["user_id"], 50)
    return render_template("digests.html", digests=all_digests)


@app.route("/digests/<int:digest_id>")
@login_required
def view_digest(digest_id):
    digest = models.get_digest(digest_id, session["user_id"])
    if not digest:
        flash("Digest not found.", "error")
        return redirect(url_for("digests"))
    return render_template("digest_view.html", digest=digest)


# --- Run Now ---

@app.route("/run", methods=["POST"])
@login_required
def run_now():
    try:
        total = run_searches_for_user(session["user_id"])
        if total > 0:
            flash(f"Found {total} new paper{'s' if total != 1 else ''}! Check Digests.", "success")
        else:
            flash("No new papers found.", "info")
    except Exception as e:
        flash(f"Search failed: {e}", "error")
    return redirect(url_for("index"))


# --- Template filter ---

@app.template_filter("nl2br")
def nl2br_filter(s):
    if not s:
        return s
    return Markup(s.replace("\n", "<br>"))


if __name__ == "__main__":
    models.init_db()
    start_scheduler()
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)

"""Send the HTML digest via SMTP."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import EmailConfig

logger = logging.getLogger(__name__)


def send_digest(email_config: EmailConfig, subject: str, html_body: str):
    """Send an HTML email digest to all configured recipients."""
    if not email_config.sender or not email_config.recipients:
        logger.error("Email sender or recipients not configured")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_config.sender
    msg["To"] = ", ".join(email_config.recipients)

    # Plain text fallback
    plain_text = "Your weekly literature digest is ready. View this email in an HTML-capable client."
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if email_config.use_tls:
            server = smtplib.SMTP(email_config.smtp_host, email_config.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(email_config.smtp_host, email_config.smtp_port)

        if email_config.password:
            server.login(email_config.sender, email_config.password)

        server.sendmail(email_config.sender, email_config.recipients, msg.as_string())
        server.quit()
        logger.info(f"Digest sent to {', '.join(email_config.recipients)}")
    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email: {e}")
        raise

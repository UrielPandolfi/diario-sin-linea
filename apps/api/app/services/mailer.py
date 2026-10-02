"""Envío SMTP opcional. Si falta configuración, no afirma que salió un correo."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)


def mail_configured(settings: Settings) -> bool:
    host = (settings.smtp_host or "").strip()
    sender = (settings.smtp_from or "").strip()
    origin = (settings.site_url or "").strip()
    return bool(host and sender and origin.startswith(("http://", "https://")))


def send_email(settings: Settings, *, to: str, subject: str, body: str) -> bool:
    if not mail_configured(settings):
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from.strip()
    message["To"] = to
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host.strip(), int(settings.smtp_port), timeout=15) as client:
            if settings.smtp_tls:
                client.starttls()
            username = (settings.smtp_username or "").strip()
            if username:
                client.login(username, settings.smtp_password or "")
            client.send_message(message)
    except Exception:
        logger.exception("smtp send failed")
        return False
    return True

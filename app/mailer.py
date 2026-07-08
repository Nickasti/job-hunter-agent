"""
app/mailer.py — Invio email transazionali via Gmail SMTP (gratuito).

Usato per il recupero password. Serve una "App Password" di Google (non la
password normale dell'account): si genera da myaccount.google.com/apppasswords
con la verifica in due passaggi attiva. Vedi README_PLATFORM.md.

Se SMTP_USER/SMTP_PASSWORD non sono configurati (es. sviluppo locale), il link
viene solo loggato/stampato invece di essere spedito, così si può testare il
flusso senza credenziali email reali.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from app import config_web

log = logging.getLogger("app.mailer")


def send_email(to: str, subject: str, html_body: str) -> bool:
    ok, _detail = send_email_diag(to, subject, html_body)
    return ok


def send_email_diag(to: str, subject: str, html_body: str) -> tuple[bool, str]:
    """Come send_email, ma ritorna anche il dettaglio dell'esito (per diagnosi)."""
    if not config_web.SMTP_USER or not config_web.SMTP_PASSWORD:
        msg = "SMTP non configurato (SMTP_USER/SMTP_PASSWORD mancanti): email NON inviata (solo log)."
        log.warning("%s Destinatario=%s oggetto=%s", msg, to, subject)
        log.info("Contenuto email (dev fallback):\n%s", html_body)
        return False, msg

    msg_obj = MIMEText(html_body, "html", "utf-8")
    msg_obj["Subject"] = subject
    msg_obj["From"] = config_web.SMTP_FROM or config_web.SMTP_USER
    msg_obj["To"] = to

    try:
        with smtplib.SMTP(config_web.SMTP_HOST, config_web.SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(config_web.SMTP_USER, config_web.SMTP_PASSWORD)
            server.sendmail(config_web.SMTP_FROM or config_web.SMTP_USER, [to], msg_obj.as_string())
        log.info("Email inviata a %s: %s", to, subject)
        return True, "inviata con successo"
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Invio email fallito verso %s: %s", to, exc)
        return False, f"{type(exc).__name__}: {exc}"


def build_reset_email(reset_url: str, ttl_minutes: int) -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;color:#161512;">
  <h2 style="font-family:Arial,sans-serif;">VeredAI</h2>
  <p>Hai richiesto di reimpostare la password del tuo account.</p>
  <p style="margin:24px 0;">
    <a href="{reset_url}"
       style="background:#161512;color:#fff;padding:12px 22px;border-radius:10px;
              text-decoration:none;font-weight:600;display:inline-block;">
      Imposta una nuova password
    </a>
  </p>
  <p style="color:#66735c;font-size:.9rem;">
    Il link scade tra {ttl_minutes} minuti. Se non hai richiesto tu il reset, ignora questa email:
    la tua password resterà invariata.
  </p>
</div>
"""

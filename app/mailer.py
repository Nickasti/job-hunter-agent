"""
app/mailer.py — Invio email transazionali via Brevo (ex Sendinblue), API HTTPS.

Usato per il recupero password. Gratis (300 email/giorno), nessuna carta
richiesta: serve solo un account Brevo con un "mittente" verificato (un click
su un'email di conferma, non un intero dominio) e una API key.

Perché HTTPS e non SMTP diretto: SMTP (porta 587) da Render free tier è
inaffidabile — verificato con fallimenti intermittenti ("Network is
unreachable") e timeout totali. L'API di Brevo usa HTTPS (porta 443), la
stessa che l'app già usa con successo per Telegram/Gemini/Google.

Se BREVO_API_KEY non è configurata (es. sviluppo locale), il link viene solo
loggato invece di essere spedito, così si può testare il flusso senza
credenziali reali.
"""
from __future__ import annotations

import logging

import requests

from app import config_web

log = logging.getLogger("app.mailer")

_BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(to: str, subject: str, html_body: str) -> bool:
    ok, _detail = send_email_diag(to, subject, html_body)
    return ok


def send_email_diag(to: str, subject: str, html_body: str) -> tuple[bool, str]:
    """Come send_email, ma ritorna anche il dettaglio dell'esito (per diagnosi)."""
    if not config_web.BREVO_API_KEY:
        msg = "BREVO_API_KEY non configurata: email NON inviata (solo log)."
        log.warning("%s Destinatario=%s oggetto=%s", msg, to, subject)
        log.info("Contenuto email (dev fallback):\n%s", html_body)
        return False, msg

    payload = {
        "sender": {"name": config_web.BREVO_SENDER_NAME, "email": config_web.BREVO_SENDER_EMAIL},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html_body,
    }
    headers = {
        "api-key": config_web.BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        r = requests.post(_BREVO_API_URL, json=payload, headers=headers, timeout=20)
        if r.status_code in (200, 201):
            log.info("Email inviata a %s: %s", to, subject)
            return True, "inviata con successo (Brevo API)"
        detail = f"HTTP {r.status_code}: {r.text[:300]}"
        log.error("Invio email fallito verso %s: %s", to, detail)
        return False, detail
    except requests.RequestException as exc:
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

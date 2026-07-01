"""
notifier/telegram.py — Invio notifiche su Telegram (Bot API, gratuita).

Usa MarkdownV2 con escaping rigoroso: tutti i campi dinamici vengono
"sanitizzati" perché un solo carattere speciale non escapato fa fallire
l'intero messaggio con errore 400 da Telegram.
"""
from __future__ import annotations

import logging
import time

import requests

import config

log = logging.getLogger("notifier.telegram")

_API = "https://api.telegram.org/bot{token}/sendMessage"

# Caratteri che MarkdownV2 richiede di escapare con backslash.
_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def escape_md(text: str | None) -> str:
    """Escapa un testo per MarkdownV2."""
    if not text:
        return ""
    out = []
    for ch in str(text):
        if ch in _MDV2_SPECIAL:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def build_message(result: dict) -> str:
    """
    Costruisce il messaggio Markdown dal dizionario di scoring.

    `result` contiene i campi prodotti dal gemini_scorer:
    title, company, source_emoji, location, language, contract_type,
    duration, salary, score, match_reasons, why_check, url.
    """
    e = escape_md
    title = e(result.get("title", "Senza titolo"))
    score = e(str(result.get("score", "?")))
    company = e(result.get("company", "?"))
    src = result.get("source_emoji", "")
    location = e(result.get("location") or "n/d")
    language = e(result.get("language") or "n/d")
    contract = e(result.get("contract_type") or "n/d")
    duration = e(result.get("duration") or "n/d")
    salary = e(result.get("salary") or "Non menzionata")
    reasons = e(result.get("match_reasons") or "—")
    why = e(result.get("why_check") or "—")
    url = result.get("url") or ""

    lines = [
        f"🎯 *{title}* — Score: {score}/100",
        f"🏢 {company} {src}".rstrip(),
        f"📍 {location}",
        f"🗣 {language} • 📝 {contract} • ⏱ {duration}",
        f"💰 {salary}",
        "",
        f"💡 {reasons}",
        "",
        f"⚠️ Verifica: {why}",
    ]
    if url:
        # L'URL come link evita problemi di escaping nel corpo.
        lines += ["", f"🔗 [Apri annuncio]({e(url)})"]
    return "\n".join(lines)


def send(result: dict, *, retries: int = 3) -> bool:
    """Invia la notifica. Ritorna True se consegnata."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("Telegram non configurato (token/chat_id mancanti).")
        return False

    text = build_message(result)
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }
    url = _API.format(token=config.TELEGRAM_BOT_TOKEN)

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 200:
                log.info("Notifica inviata: %s", result.get("title"))
                return True
            if r.status_code == 429:
                wait = int(r.json().get("parameters", {}).get("retry_after", 5))
                log.warning("Telegram rate limit, attendo %ss", wait)
                time.sleep(wait)
                continue
            log.error("Telegram errore %s: %s", r.status_code, r.text[:300])
        except requests.RequestException as exc:
            log.warning("Telegram tentativo %s fallito: %s", attempt, exc)
        time.sleep(2 * attempt)
    return False


def send_plain(text: str) -> bool:
    """Invia un messaggio di testo semplice (per log/errori operativi)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        r = requests.post(
            _API.format(token=config.TELEGRAM_BOT_TOKEN),
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=config.HTTP_TIMEOUT,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False

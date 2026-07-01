"""
app/telegram_bot.py — Bot Telegram CONDIVISO della piattaforma.

Un solo bot per tutti gli utenti (nessun BotFather lato utente). Il collegamento
avviene con un deep-link: t.me/<bot>?start=<link_code>. Quando l'utente preme
"Avvia", Telegram invia "/start <link_code>": il webhook (o /telegram/poll)
associa il suo chat_id all'account che possiede quel codice.
"""
from __future__ import annotations

import logging
import secrets

import requests

from app import config_web

log = logging.getLogger("app.telegram")

_API = "https://api.telegram.org/bot{token}/{method}"


def new_link_code() -> str:
    """Codice univoco per il deep-link di collegamento."""
    return secrets.token_urlsafe(12)


def deep_link(link_code: str) -> str:
    user = config_web.TELEGRAM_BOT_USERNAME or "bot"
    return f"https://t.me/{user}?start={link_code}"


def _call(method: str, payload: dict) -> dict | None:
    if not config_web.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN mancante.")
        return None
    url = _API.format(token=config_web.TELEGRAM_BOT_TOKEN, method=method)
    try:
        r = requests.post(url, json=payload, timeout=20)
        data = r.json()
        if not data.get("ok"):
            log.warning("Telegram %s errore: %s", method, data)
        return data
    except requests.RequestException as exc:
        log.warning("Telegram %s fallito: %s", method, exc)
        return None


# ------------------------------------------------------------------ invio
def send_message(chat_id: str, text: str, markdown: bool = True) -> bool:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }
    if markdown:
        payload["parse_mode"] = "MarkdownV2"
    data = _call("sendMessage", payload)
    return bool(data and data.get("ok"))


# ------------------------------------------------------------------ webhook
def set_webhook() -> dict | None:
    """Registra il webhook verso PUBLIC_BASE_URL + TELEGRAM_WEBHOOK_PATH."""
    url = config_web.PUBLIC_BASE_URL + config_web.TELEGRAM_WEBHOOK_PATH
    return _call(
        "setWebhook",
        {
            "url": url,
            "secret_token": config_web.TELEGRAM_WEBHOOK_SECRET,
            "allowed_updates": ["message"],
        },
    )


def delete_webhook() -> dict | None:
    return _call("deleteWebhook", {})


def get_updates(offset: int | None = None) -> list[dict]:
    """Fallback per test locale senza webhook (long polling manuale)."""
    payload = {"timeout": 0}
    if offset is not None:
        payload["offset"] = offset
    data = _call("getUpdates", payload) or {}
    return data.get("result", []) if data.get("ok") else []


def extract_start_code(update: dict) -> tuple[str, str] | None:
    """
    Da un update Telegram estrae (chat_id, link_code) se è un "/start <code>".
    Ritorna None se non pertinente.
    """
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        return None
    return str(chat_id), code

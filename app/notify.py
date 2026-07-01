"""
app/notify.py — Formattazione e invio della notifica di match su Telegram.

Usa il bot condiviso (app.telegram_bot) inviando al chat_id del singolo utente.
Messaggio in MarkdownV2 con escaping rigoroso.
"""
from __future__ import annotations

from app import telegram_bot

_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def escape_md(text) -> str:
    if text is None:
        return ""
    out = []
    for ch in str(text):
        out.append("\\" + ch if ch in _MDV2_SPECIAL else ch)
    return "".join(out)


def build_message(result: dict) -> str:
    e = escape_md
    title = e(result.get("title", "Senza titolo"))
    score = e(str(result.get("score", "?")))
    company = e(result.get("company", "?"))
    src = result.get("source_emoji", "📧")
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
        lines += ["", f"🔗 [Apri annuncio]({e(url)})"]
    return "\n".join(lines)


def send_match(chat_id: str, result: dict) -> bool:
    """Invia la notifica del match al chat Telegram dell'utente."""
    return telegram_bot.send_message(chat_id, build_message(result), markdown=True)


def send_plain(chat_id: str, text: str) -> bool:
    return telegram_bot.send_message(chat_id, text, markdown=False)

"""
tools/get_telegram_chat_id.py — Trova il tuo TELEGRAM_CHAT_ID.

1. Crea il bot con @BotFather e copia il token.
2. Apri una chat col tuo bot e invia un messaggio qualsiasi (es. "ciao").
3. Esegui:  python tools/get_telegram_chat_id.py <BOT_TOKEN>
   (oppure imposta TELEGRAM_BOT_TOKEN nel .env e lancialo senza argomenti)
"""
from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Uso: python tools/get_telegram_chat_id.py <BOT_TOKEN>")
        return 1

    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    data = r.json()
    if not data.get("ok"):
        print("Errore:", data)
        return 1

    updates = data.get("result", [])
    if not updates:
        print("Nessun messaggio trovato. Scrivi 'ciao' al tuo bot e riprova.")
        return 1

    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")

    print("Chat ID trovati:")
    for cid, name in chats.items():
        print(f"  TELEGRAM_CHAT_ID={cid}   ({name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

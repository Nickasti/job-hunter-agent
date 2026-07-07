"""
app/config_web.py — Configurazione della piattaforma web multi-utente.

Tutte le variabili arrivano dall'ambiente (in locale da .env, in produzione
dalle env vars dell'hosting). Nessun segreto hardcoded.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ Database
# In locale SQLite su volume (data/, gitignored). In produzione Postgres:
#   postgresql+psycopg://user:pass@host/dbname
DATABASE_URL = _get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")

# ------------------------------------------------------------------ Sicurezza
# Segreto per firmare i cookie di sessione.
SESSION_SECRET = _get("SESSION_SECRET", "dev-insecure-change-me")
# Chiave Fernet per cifrare i token at-rest (generane una con:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
MASTER_KEY = _get("MASTER_KEY")
# Bearer token per proteggere POST /api/run-cycle.
RUN_CYCLE_TOKEN = _get("RUN_CYCLE_TOKEN", "dev-run-token")
# Email dell'amministratore: solo questo utente (loggato) può vedere /admin.
ADMIN_EMAIL = (_get("ADMIN_EMAIL", "niko.asti@gmail.com") or "").lower()

# ------------------------------------------------------------------ URL pubblico
# URL pubblico dell'app (assegnato da Render/Railway/Fly). Serve per il
# redirect OAuth di Google e per il webhook Telegram. Niente slash finale.
PUBLIC_BASE_URL = (_get("PUBLIC_BASE_URL", "http://localhost:8000") or "").rstrip("/")

# ------------------------------------------------------------------ Google OAuth (condiviso)
GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GOOGLE_REDIRECT_PATH = "/auth/google/callback"

# ------------------------------------------------------------------ Telegram (bot condiviso)
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = _get("TELEGRAM_BOT_USERNAME")  # senza @, es. Isola_ai_agent_bot
TELEGRAM_WEBHOOK_PATH = "/telegram/webhook"
# Segreto che Telegram rimanda nell'header per validare il webhook.
# Telegram ammette SOLO [A-Za-z0-9_-]: sanitizziamo qualunque valore arrivi
# dall'ambiente (es. auto-generato da Render con caratteri non ammessi),
# in modo coerente tra registrazione (setWebhook) e verifica dell'header.
import re as _re  # noqa: E402

TELEGRAM_WEBHOOK_SECRET = _re.sub(
    r"[^A-Za-z0-9_-]", "-", _get("TELEGRAM_WEBHOOK_SECRET", "dev-tg-webhook") or ""
)[:256]

# ------------------------------------------------------------------ Gemini (condiviso)
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash-lite")

# ------------------------------------------------------------------ Fetch email
LINKEDIN_SENDERS = [
    "jobalerts-noreply@linkedin.com",
    "jobs-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
]
LINKEDIN_LOOKBACK_DAYS = _get_int("LINKEDIN_LOOKBACK_DAYS", 2)
ENABLE_LINKEDIN_ENRICH = (_get("ENABLE_LINKEDIN_ENRICH", "true") or "").lower() in ("1", "true", "yes")


def missing_required() -> list[str]:
    """Variabili indispensabili per far girare la piattaforma."""
    required = {
        "MASTER_KEY": MASTER_KEY,
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_BOT_USERNAME": TELEGRAM_BOT_USERNAME,
        "GEMINI_API_KEY": GEMINI_API_KEY,
    }
    return [k for k, v in required.items() if not v]

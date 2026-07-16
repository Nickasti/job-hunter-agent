"""
config.py — Configurazione centralizzata.

Carica le variabili da `.env` (solo in locale; in GitHub Actions le variabili
arrivano direttamente dall'ambiente / Secrets). Non contiene segreti hardcoded.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# In locale carica .env; in CI il file non esiste e load_dotenv è un no-op.
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str | None = None) -> str | None:
    # Una variabile impostata ma VUOTA (tipico su GitHub Actions con vars non
    # valorizzate) deve comportarsi come "non impostata" → usa il default.
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name, str(default))
    return str(raw).lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- Gemini
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash-lite")
# Modello di riserva: quota gratuita SEPARATA per modello. Se il primario si
# esaurisce (429), lo scorer passa a questo per il resto del ciclo.
GEMINI_FALLBACK_MODEL = _get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
GEMINI_MIN_INTERVAL = _get_float("GEMINI_MIN_INTERVAL", 4.5)
GEMINI_MAX_RETRIES = _get_int("GEMINI_MAX_RETRIES", 5)
GEMINI_MAX_CALLS_PER_RUN = _get_int("GEMINI_MAX_CALLS_PER_RUN", 80)

# ---------------------------------------------------------------- Telegram
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# ---------------------------------------------------------------- Gmail OAuth
GMAIL_CLIENT_ID = _get("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = _get("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = _get("GMAIL_REFRESH_TOKEN")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
LINKEDIN_SENDERS = [
    "jobalerts-noreply@linkedin.com",
    "jobs-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
]
LINKEDIN_LOOKBACK_DAYS = _get_int("LINKEDIN_LOOKBACK_DAYS", 2)

# ---------------------------------------------------------------- Comportamento
SCORE_THRESHOLD = _get_int("SCORE_THRESHOLD", 55)
SCORE_CACHE_DAYS = _get_int("SCORE_CACHE_DAYS", 30)
ENABLE_PLAYWRIGHT = _get_bool("ENABLE_PLAYWRIGHT", True)
ENABLE_LINKEDIN_ENRICH = _get_bool("ENABLE_LINKEDIN_ENRICH", True)
# Interruttori per fonte (utili per test mirati / debug).
ENABLE_GMAIL = _get_bool("ENABLE_GMAIL", True)
ENABLE_SCRAPING = _get_bool("ENABLE_SCRAPING", True)

# ---------------------------------------------------------------- Percorsi
DB_PATH = _get("DB_PATH") or str(BASE_DIR / "storage" / "jobs.db")
COMPANIES_PATH = str(BASE_DIR / "companies.yaml")
LOG_DIR = BASE_DIR / "logs"

# ---------------------------------------------------------------- Scraping
# User-Agent realistico per evitare blocchi banali; rispettiamo comunque robots.txt.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 25
# Spaziatura minima tra richieste verso linkedin.com (ToS-friendly)
LINKEDIN_REQUEST_INTERVAL = 5.0
# Spaziatura minima tra due richieste browser allo STESSO dominio (Playwright).
SCRAPE_MIN_INTERVAL = _get_float("SCRAPE_MIN_INTERVAL", 15.0)
RESPECT_ROBOTS = True


def validate(require_gmail: bool = True) -> list[str]:
    """Ritorna la lista di variabili obbligatorie mancanti (vuota = ok)."""
    missing = []
    required = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    if require_gmail:
        required.update(
            {
                "GMAIL_CLIENT_ID": GMAIL_CLIENT_ID,
                "GMAIL_CLIENT_SECRET": GMAIL_CLIENT_SECRET,
                "GMAIL_REFRESH_TOKEN": GMAIL_REFRESH_TOKEN,
            }
        )
    for name, value in required.items():
        if not value:
            missing.append(name)
    return missing

"""
test_run.py — Test end-to-end MINIMO senza chiamare Gemini né Telegram reali.

Verifica che la pipeline (dedup → scoring → costruzione messaggio) funzioni su
un job di esempio, usando un mock dello scorer e un DB SQLite temporaneo.

Esegui:  python test_run.py
"""
from __future__ import annotations

import sys
import tempfile
import os

# Console Windows (cp1252) → forza UTF-8 per stampare le emoji senza crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from models import Job
from notifier import telegram
from storage.db import Database


def fake_score(job: Job) -> dict:
    """Mock del risultato Gemini (nessuna chiamata di rete)."""
    return {
        "score": 78,
        "language": "Inglese",
        "contract_type": "Curricular internship",
        "duration": "6 mesi",
        "salary": "Non menzionata",
        "skills_match": "forte",
        "match_reasons": "Stage in marketing analytics con CRM e Python: ottimo match.",
        "why_check": "Conferma che accettino convenzione di stage curricolare.",
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": job.source,
        "source_emoji": job.source_emoji,
    }


def main() -> int:
    print("== test_run: pipeline end-to-end (mock) ==\n")

    job = Job(
        title="Marketing Data Analyst Intern (m/f/d)",
        company="Talkdesk",
        location="Lisbon, Portugal",
        url="https://boards.greenhouse.io/talkdesk/jobs/123456?utm_source=x",
        description="Curricular internship, 6 months. SQL, Python, CRM, marketing automation.",
        source="scrape",
    )

    # --- DB temporaneo ---
    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "test.db"))

    h = job.fingerprint()
    assert not db.is_known(h), "Il job non dovrebbe ancora essere noto."
    print(f"[ok] fingerprint stabile: {h[:12]}...")

    # --- Scoring mock ---
    result = fake_score(job)
    print(f"[ok] score mock: {result['score']} (soglia 55)")
    assert result["score"] >= 55

    # --- Costruzione messaggio Telegram (senza inviare) ---
    msg = telegram.build_message(result)
    print("\n--- Anteprima messaggio Telegram (MarkdownV2) ---")
    print(msg)
    print("--- fine anteprima ---\n")
    assert "Talkdesk" in msg
    assert "Score: 78" in msg

    # --- Persistenza + dedup ---
    db.save_job(job, score=result["score"], score_json=result, notified=True)
    assert db.is_known(h), "Dopo il save il job deve risultare noto."
    assert db.was_notified(h), "Deve risultare notificato."
    cached = db.get_cached_score(h, cache_days=30)
    assert cached and cached["score"] == 78, "La cache score deve restituire 78."
    print("[ok] dedup + cache score funzionanti.")

    db.close()
    print("\n✅ TEST PASSATO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

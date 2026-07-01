"""
main.py — Entry point in modalità SINGLE-RUN (per GitHub Actions).

Esegue UN giro completo e termina con un exit code:
  0 = run completato (con o senza notifiche)
  1 = errore di configurazione (variabili mancanti)
  2 = errore fatale imprevisto

Flow:
  1. Valida la configurazione.
  2. Fetch job da Gmail (LinkedIn alerts) e da scraping career page.
  3. Per ogni job: dedup → (cache score | pre-filtro | Gemini) → notifica se >= soglia.
  4. Salva tutto su SQLite (anche gli scartati, per la dedup futura).

La schedulazione è esterna (cron di GitHub Actions, ogni ora).
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import config
from models import Job
from notifier import telegram
from scoring.gemini_scorer import GeminiScorer, QuotaExhausted
from sources import company_scraper, gmail_source
from storage.db import Database

log = logging.getLogger("main")


# ----------------------------------------------------------------- logging
def setup_logging() -> None:
    # Console Windows (cp1252) → forza UTF-8 per i log con emoji.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        config.LOG_DIR / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Riduci il rumore delle librerie esterne.
    for noisy in ("googleapiclient", "google_auth_httplib2", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ----------------------------------------------------------------- collect
def collect_jobs(db: Database) -> list[Job]:
    """Raccoglie i job dalle due fonti, isolando i fallimenti."""
    jobs: list[Job] = []

    if config.ENABLE_GMAIL:
        try:
            email_jobs = gmail_source.fetch_jobs(db)
            jobs.extend(email_jobs)
        except Exception as exc:  # noqa: BLE001
            log.error("Fonte Gmail fallita: %s", exc)
    else:
        log.info("Fonte Gmail disabilitata (ENABLE_GMAIL=false).")

    if config.ENABLE_SCRAPING:
        try:
            scraped = company_scraper.fetch_jobs()
            jobs.extend(scraped)
        except Exception as exc:  # noqa: BLE001
            log.error("Fonte scraping fallita: %s", exc)
    else:
        log.info("Fonte scraping disabilitata (ENABLE_SCRAPING=false).")

    log.info("Totale job raccolti (pre-dedup): %d", len(jobs))
    return jobs


# ----------------------------------------------------------------- process
def process_jobs(db: Database, jobs: list[Job]) -> dict:
    scorer = GeminiScorer()
    stats = {"new": 0, "cached": 0, "prefiltered": 0, "scored": 0,
             "notified": 0, "skipped_known": 0, "queued_quota": 0}

    for job in jobs:
        h = job.fingerprint()

        # 1) Cache: già scorato di recente?
        cached = db.get_cached_score(h, config.SCORE_CACHE_DAYS)
        if cached is not None:
            stats["cached"] += 1
            # Già noto e già valutato: non rinotifichiamo (gestito da notified).
            continue

        # 2) Job già visto ma senza score valido in cache → comunque salta se
        #    già notificato (evita spam); altrimenti procede a (ri)scorare.
        known = db.is_known(h)
        if known and db.was_notified(h):
            stats["skipped_known"] += 1
            continue

        if not known:
            stats["new"] += 1

        # 3) Pre-filtro locale (risparmia quota Gemini).
        result = GeminiScorer.prefilter(job)
        if result is not None:
            stats["prefiltered"] += 1
            db.save_job(job, score=result["score"], score_json=result, notified=False)
            continue

        # 4) Scoring Gemini.
        try:
            result = scorer.score(job)
            stats["scored"] += 1
        except QuotaExhausted:
            # Quota finita: NON salviamo questo job → verrà riprovato al prossimo
            # run. Interrompiamo lo scoring ma lasciamo concludere il run.
            log.warning("Quota Gemini esaurita: i job restanti slittano al prossimo run.")
            stats["queued_quota"] += 1
            break
        except Exception as exc:  # noqa: BLE001
            log.error("Scoring fallito per '%s': %s", job.title, exc)
            continue

        # 5) Notifica se sopra soglia.
        notified = False
        if result["score"] >= config.SCORE_THRESHOLD:
            notified = telegram.send(result)
            if notified:
                stats["notified"] += 1

        # 6) Persisti (anche score bassi, per dedup futura).
        db.save_job(job, score=result["score"], score_json=result, notified=notified)

    return stats


# ----------------------------------------------------------------- main
def main() -> int:
    setup_logging()
    log.info("=" * 60)
    log.info("job-hunter-agent — avvio run single-shot")

    missing = config.validate(require_gmail=True)
    if missing:
        log.error("Variabili mancanti: %s", ", ".join(missing))
        return 1

    db = Database(config.DB_PATH)
    try:
        jobs = collect_jobs(db)
        stats = process_jobs(db, jobs)
        log.info("Riepilogo run: %s", stats)
    except Exception as exc:  # noqa: BLE001
        log.exception("Errore fatale: %s", exc)
        return 2
    finally:
        db.close()

    log.info("Run completato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

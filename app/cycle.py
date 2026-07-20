"""
app/cycle.py — Esecuzione di UN ciclo completo (multi-utente).

Chiamato da POST /api/run-cycle (Fase 5). Passi:
  1. FETCH: per ogni utente con Gmail collegato, scarica nuove email → user_jobs.
  2. SCORING: per ogni utente attivo, valuta i job non ancora valutati con i SUOI
     criteri (budget Gemini GLOBALE), salva in user_matches (= cache anti-ricalcolo).
  3. NOTIFICA: invia su Telegram i match sopra la soglia dell'utente, una volta sola.

Se la quota Gemini si esaurisce, lo scoring si ferma: i job restanti verranno
valutati al ciclo successivo (nessun dato perso, sono già in user_jobs).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select

import config
from app import config_web, crypto, top_companies
from app.db import session_scope
from app.gmail_fetch import fetch_new_jobs
from app.models_db import (
    RunLog,
    User,
    UserGoogleToken,
    UserJob,
    UserMatch,
)
from app.notify import send_match, send_plain
from app.scoring_engine import CycleScorer, QuotaExhausted
from models import Job

log = logging.getLogger("app.cycle")

# Lucchetto anti-concorrenza: il cron GitHub fa --retry e più trigger possono
# sovrapporsi. Due cicli in parallelo rifanno lo stesso fetch e si scontrano sui
# vincoli unici del DB (rollback a vicenda). Un ciclo alla volta per processo.
_cycle_lock = threading.Lock()


def _job_from_row(row: UserJob) -> Job:
    return Job(
        title=row.titolo,
        company=row.azienda,
        location=row.location,
        url=row.url,
        description=row.testo_grezzo or row.titolo,
        source=row.fonte or "gmail",
    )


def run_cycle() -> dict:
    if not _cycle_lock.acquire(blocking=False):
        log.info("Ciclo già in corso: salto questa esecuzione (anti-concorrenza).")
        return {"skipped": "already_running"}
    try:
        return _run_cycle_locked()
    finally:
        _cycle_lock.release()


def _run_cycle_locked() -> dict:
    stats = {"users": 0, "fetched": 0, "scored": 0, "notified": 0, "quota_stop": False}
    started = datetime.now(timezone.utc)
    detail_lines: list[str] = []

    with session_scope() as db:
        # Detail dell'ULTIMO ciclo: serve a non ripetere ogni ora l'avviso
        # Telegram "Gmail scollegato" (lo mandiamo solo al primo fallimento).
        last_run = db.scalars(
            select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
        ).first()
        last_detail = (last_run.detail or "") if last_run else ""

        # ------------------------------------------------ 1) FETCH per utente
        gtokens = db.scalars(select(UserGoogleToken)).all()
        for gt in gtokens:
            user = db.get(User, gt.user_id)
            if not user:
                continue
            try:
                refresh = crypto.decrypt(gt.refresh_token_enc)
                jobs, new_epoch = fetch_new_jobs(refresh, gt.last_gmail_epoch)
            except Exception as exc:  # noqa: BLE001 — isolamento per utente
                log.warning("Fetch fallito per user %s: %s", user.id, exc)
                marker = f"user {user.id}: gmail_token_invalid"
                if "invalid_grant" in str(exc):
                    detail_lines.append(marker)
                    # Avvisa l'utente UNA volta (non a ogni ciclo orario).
                    chat_id = user.telegram.chat_id if user.telegram else None
                    if chat_id and marker not in last_detail:
                        send_plain(
                            chat_id,
                            "⚠️ VeredAI: il collegamento con Gmail è scaduto, quindi "
                            "non ricevo più i tuoi annunci. Vai sulla dashboard "
                            f"({config_web.PUBLIC_BASE_URL}/dashboard) e ricollega "
                            "Gmail per riattivare le notifiche.",
                        )
                else:
                    detail_lines.append(f"user {user.id}: fetch error {exc}")
                continue

            existing = set(
                db.scalars(
                    select(UserJob.fingerprint).where(UserJob.user_id == user.id)
                ).all()
            )
            added = 0
            for j in jobs:
                fp = j.fingerprint()
                if fp in existing:
                    continue
                existing.add(fp)
                db.add(
                    UserJob(
                        user_id=user.id,
                        fonte="gmail",
                        url=j.url,
                        titolo=j.title,
                        azienda=j.company,
                        location=j.location,
                        testo_grezzo=j.description,
                        fingerprint=fp,
                    )
                )
                added += 1
            gt.last_gmail_epoch = new_epoch
            # COMMIT per-utente: job persistiti e watermark avanzato SUBITO. Così,
            # se lo scoring (lungo) viene interrotto, l'arretrato Gmail non viene
            # riscaricato al ciclo dopo — si drena invece di ripartire da zero.
            db.commit()
            stats["fetched"] += added
            log.info("User %s: %d nuovi job (commit)", user.id, added)

        # ---------------------------------- 1-bis) FETCH career page (Fonte 2)
        # Lo scraping è GLOBALE (una sola passata browser per tutte le aziende
        # di companies.yaml), poi i job vengono accreditati a ogni utente
        # attivo con dedup via fingerprint — lo scoring resta per-utente.
        if config.ENABLE_SCRAPING:
            try:
                from sources.company_scraper import fetch_jobs as fetch_company_jobs

                scraped = fetch_company_jobs()
                log.info("Scraping career page: %d job trovati", len(scraped))
                active = db.scalars(select(User).where(User.is_active.is_(True))).all()
                for user in active:
                    existing = set(
                        db.scalars(
                            select(UserJob.fingerprint).where(UserJob.user_id == user.id)
                        ).all()
                    )
                    for j in scraped:
                        fp = j.fingerprint()
                        if fp in existing:
                            continue
                        existing.add(fp)
                        db.add(
                            UserJob(
                                user_id=user.id,
                                fonte="scrape",
                                url=j.url,
                                titolo=j.title,
                                azienda=j.company,
                                location=j.location,
                                testo_grezzo=j.description,
                                fingerprint=fp,
                            )
                        )
                        stats["fetched"] += 1
                db.commit()
            except Exception as exc:  # noqa: BLE001 — lo scraping non blocca il ciclo
                db.rollback()
                log.warning("Scraping career page fallito: %s", exc)
                detail_lines.append(f"scrape error: {exc}")

        # ------------------------------------------------ 2+3) SCORING + NOTIFICA
        scorer = CycleScorer()  # UNA istanza → budget/throttle GLOBALE
        active_users = db.scalars(select(User).where(User.is_active.is_(True))).all()

        for user in active_users:
            if stats["quota_stop"]:
                break
            criteria = user.criteria
            if criteria is None:
                continue
            chat_id = user.telegram.chat_id if user.telegram else None
            # Marcatura "azienda top": funzione riservata all'utente admin.
            mark_top = user.email == config_web.ADMIN_EMAIL
            stats["users"] += 1

            # Job dell'utente ancora senza match (non valutati).
            scored_job_ids = set(
                db.scalars(
                    select(UserMatch.job_id).where(UserMatch.user_id == user.id)
                ).all()
            )
            rows = db.scalars(select(UserJob).where(UserJob.user_id == user.id)).all()
            for row in rows:
                if row.id in scored_job_ids:
                    continue
                job = _job_from_row(row)
                try:
                    result = scorer.evaluate(job, criteria)
                except QuotaExhausted:
                    log.warning("Quota Gemini esaurita: stop scoring, resto al prossimo ciclo.")
                    stats["quota_stop"] = True
                    break
                except Exception as exc:  # noqa: BLE001
                    log.error("Scoring fallito (user %s job %s): %s", user.id, row.id, exc)
                    continue

                stats["scored"] += 1
                notified_at = None
                if result["score"] >= (criteria.soglia_notifica or 55) and chat_id:
                    top = (
                        top_companies.match_top_company(
                            job.company, job.title, job.description
                        )
                        if mark_top
                        else None
                    )
                    if send_match(chat_id, result, top_company=top):
                        notified_at = datetime.now(timezone.utc)
                        stats["notified"] += 1

                db.add(
                    UserMatch(
                        user_id=user.id,
                        job_id=row.id,
                        score=result["score"],
                        dettaglio_score=json.dumps(result, ensure_ascii=False),
                        notificato_at=notified_at,
                    )
                )
                # COMMIT per-match: se ho già inviato la notifica Telegram, la
                # marcatura "notificato" dev'essere durevole SUBITO, per non
                # rischiare un doppio invio se il ciclo si interrompe più avanti.
                db.commit()

        # ------------------------------------------------ log del ciclo
        db.add(
            RunLog(
                started_at=started,
                ok=True,
                users_processed=stats["users"],
                jobs_fetched=stats["fetched"],
                jobs_scored=stats["scored"],
                notified=stats["notified"],
                detail="; ".join(detail_lines)[:2000] or None,
            )
        )

    stats["detail"] = "; ".join(detail_lines)[:2000]
    log.info("Ciclo completato: %s", stats)
    return stats

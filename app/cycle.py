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
from datetime import datetime, timezone

from sqlalchemy import select

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
from app.notify import send_match
from app.scoring_engine import CycleScorer, QuotaExhausted
from models import Job

log = logging.getLogger("app.cycle")


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
    stats = {"users": 0, "fetched": 0, "scored": 0, "notified": 0, "quota_stop": False}
    started = datetime.now(timezone.utc)
    detail_lines: list[str] = []

    with session_scope() as db:
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
            db.flush()
            stats["fetched"] += added
            log.info("User %s: %d nuovi job", user.id, added)

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
                db.flush()

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

    log.info("Ciclo completato: %s", stats)
    return stats

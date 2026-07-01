"""
app/scoring_engine.py — Scoring per-utente con budget Gemini GLOBALE.

Un solo GeminiScorer per ciclo (throttling + budget + backoff condivisi tra
tutti gli utenti, come da decisione architetturale #6). Il pre-filtro locale è
personalizzato sui criteri dell'utente (località, senior) per risparmiare quota.
La cache score è a livello di user_matches (gestita nel run-cycle).
"""
from __future__ import annotations

import logging

from models import Job
from scoring import prompts
from scoring.gemini_scorer import GeminiScorer, QuotaExhausted  # noqa: F401 (riesportato)

log = logging.getLogger("app.scoring")

_SENIOR_HINTS = (
    "senior", "sr.", "lead", "head of", "principal", "manager", "director",
    "staff engineer", "architect", "10+ years", "5+ years", "vp ",
)
_GOOD_HINTS = (
    "intern", "internship", "stage", "trainee", "estágio", "estagio",
    "junior", "jr.", "graduate", "entry level", "entry-level", "working student",
    "curricular", "curricolare", "apprentice",
)


def _csv(value: str) -> list[str]:
    return [t.strip().lower() for t in (value or "").replace(";", ",").split(",") if t.strip()]


def prefilter(job: Job, criteria) -> dict | None:
    """
    Filtro locale personalizzato. Ritorna un dict di scarto (score 0) se il job
    è palesemente non pertinente ai criteri dell'utente, altrimenti None
    (→ va valutato da Gemini). Volutamente prudente: sulle skill lascia
    decidere Gemini per non scartare per errore titoli poveri di descrizione.
    """
    blob = f"{job.title} {job.location} {job.description}".lower()

    # Località: se l'utente ha indicato località e nessuna compare → scarta.
    locations = _csv(getattr(criteria, "location_filter", ""))
    if locations and not any(loc in blob for loc in locations):
        return _discard(job, "Località non compatibile coi criteri (pre-filtro locale).")

    # Senior evidente e nessun segnale junior/stage → scarta.
    title_blob = f"{job.title} {job.description}".lower()
    if any(h in title_blob for h in _SENIOR_HINTS) and not any(
        h in title_blob for h in _GOOD_HINTS
    ):
        return _discard(job, "Profilo chiaramente senior/manager (pre-filtro locale).")

    return None


class CycleScorer:
    """Wrapper attorno a un unico GeminiScorer (budget globale per ciclo)."""

    def __init__(self):
        self.gemini = GeminiScorer()

    @property
    def calls_made(self) -> int:
        return self.gemini._calls_made

    def evaluate(self, job: Job, criteria) -> dict:
        """Pre-filtro locale → Gemini con prompt parametrico dai criteri utente."""
        pre = prefilter(job, criteria)
        if pre is not None:
            return pre
        system_prompt = prompts.build_system_prompt(criteria)
        return self.gemini.score(job, system_prompt=system_prompt)


def _discard(job: Job, reason: str) -> dict:
    return _finalize(
        job,
        {
            "score": 0,
            "language": "n/d",
            "contract_type": "n/d",
            "duration": "n/d",
            "salary": "Non menzionata",
            "skills_match": "off",
            "location_ok": False,
            "match_reasons": "Scartato dal pre-filtro locale.",
            "why_check": reason,
        },
    )


def _finalize(job: Job, data: dict) -> dict:
    data = dict(data or {})
    data.setdefault("score", 0)
    try:
        data["score"] = max(0, min(100, int(data["score"])))
    except (TypeError, ValueError):
        data["score"] = 0
    data.update(
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "source": job.source,
            "source_emoji": "📧" if job.source == "gmail" else "🌐",
        }
    )
    return data

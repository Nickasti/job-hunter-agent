"""
scoring/gemini_scorer.py — Scoring degli annunci con Google Gemini (free tier).

Caratteristiche per rispettare i limiti del free tier:
  - PRE-FILTRO LOCALE: scarta i job ovviamente non pertinenti senza chiamare
    Gemini (risparmia quota).
  - THROTTLING: almeno GEMINI_MIN_INTERVAL secondi tra due chiamate.
  - RETRY con backoff esponenziale sugli errori 429 / RESOURCE_EXHAUSTED.
  - BUDGET per run: massimo GEMINI_MAX_CALLS_PER_RUN chiamate; superato il
    budget si solleva QuotaExhausted e i job rimanenti restano per il run dopo.

NB: la cache degli score (riuso entro N giorni) è gestita a monte in main.py
tramite il database, così questo modulo resta focalizzato sulla chiamata.
"""
from __future__ import annotations

import json
import logging
import re
import time

import config
from scoring import prompts

log = logging.getLogger("scoring.gemini")


class QuotaExhausted(Exception):
    """Sollevata quando la quota Gemini è esaurita per questo run."""


# Keyword usate dal pre-filtro locale (lowercase).
_SENIOR_HINTS = (
    "senior", "sr.", "lead", "head of", "principal", "manager", "director",
    "staff engineer", "architect", "10+ years", "5+ years", "vp ",
)
_GOOD_HINTS = (
    "intern", "internship", "stage", "trainee", "estágio", "estagio",
    "junior", "jr.", "graduate", "entry level", "entry-level", "working student",
    "curricular", "curricolare", "apprentice",
)
_MARKETING_HINTS = (
    "market", "martech", "crm", "data", "analyt", "growth", "digital",
    "automation", "ai ", "machine learning", "python", "sql", "social",
    "communication", "comunicazione", "brand", "campaign", "seo", "content",
)
# Località target: si accettano solo annunci riferiti a Lisbona/Portogallo.
_LOCATION_HINTS = (
    "lisbon", "lisboa", "lisbona", "portugal", "portogallo",
)


class GeminiScorer:
    def __init__(self):
        self._client = None
        self._last_call = 0.0
        self._calls_made = 0
        # Modello primario + fallback: se la quota del primario si esaurisce (429),
        # si passa automaticamente al fallback per il resto del ciclo.
        self._model = config.GEMINI_MODEL
        self._fallback = getattr(config, "GEMINI_FALLBACK_MODEL", "") or ""

    # ------------------------------------------------------------------ client
    def _get_client(self):
        if self._client is None:
            from google import genai  # import lazy: errori chiari se manca la dep

            if not config.GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY mancante.")
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    # --------------------------------------------------------------- prefilter
    @staticmethod
    def prefilter(job) -> dict | None:
        """
        Filtro locale ECONOMICO. Ritorna:
          - un dict di score "scartato" (score 0) se il job è palesemente off,
            così non sprechiamo una chiamata Gemini;
          - None se il job merita la valutazione di Gemini.
        """
        # 0) Località: scarta subito ciò che non è a Lisbona/Portogallo.
        #    Controlla anche il campo location (parsato da email/scraping).
        loc_blob = f"{job.location} {job.title} {job.description}".lower()
        if not any(h in loc_blob for h in _LOCATION_HINTS):
            return _discard(job, "Annuncio non riferito a Lisbona/Portogallo (pre-filtro locale).")

        blob = f"{job.title} {job.description}".lower()

        if any(h in blob for h in _SENIOR_HINTS) and not any(
            h in blob for h in _GOOD_HINTS
        ):
            return _discard(job, "Profilo chiaramente senior/manager (pre-filtro locale).")

        # Niente alcun aggancio a marketing/data/tech → quasi certamente off.
        if not any(h in blob for h in _MARKETING_HINTS):
            return _discard(job, "Nessuna keyword pertinente al profilo (pre-filtro locale).")

        return None

    # ------------------------------------------------------------------- score
    def score(self, job, system_prompt: str | None = None) -> dict:
        """
        Valuta un job con Gemini e ritorna il dict di scoring arricchito.
        `system_prompt` opzionale: se None usa quello legacy (single-user);
        nella piattaforma multi-utente si passa il prompt parametrico
        costruito dai criteri dell'utente. Il budget/throttling è di ISTANZA:
        creare UN solo GeminiScorer per ciclo → limite GLOBALE tra gli utenti.
        Solleva QuotaExhausted se il budget per-run è esaurito.
        """
        if self._calls_made >= config.GEMINI_MAX_CALLS_PER_RUN:
            raise QuotaExhausted("Budget chiamate Gemini per-run esaurito.")

        self._throttle()
        client = self._get_client()
        user_content = prompts.build_user_content(job)
        system_instruction = system_prompt or prompts.SYSTEM_PROMPT

        delay = 2.0
        for attempt in range(1, config.GEMINI_MAX_RETRIES + 1):
            try:
                resp = client.models.generate_content(
                    model=self._model,
                    contents=user_content,
                    config={
                        "system_instruction": system_instruction,
                        "response_mime_type": "application/json",
                        "temperature": 0.2,
                    },
                )
                self._calls_made += 1
                self._last_call = time.time()
                return _finalize(job, _parse_json(resp.text))
            except Exception as exc:  # noqa: BLE001 — la SDK usa eccezioni varie
                msg = str(exc)
                is_quota = _is_rate_limit(msg)
                is_transient = is_quota or _is_server_transient(msg)

                # Quota del modello corrente esaurita? Passa al modello di riserva
                # (la quota gratuita è SEPARATA per ogni modello) e riprova subito.
                if is_quota and self._fallback and self._model != self._fallback:
                    log.warning(
                        "Quota esaurita su %s → passo al modello di riserva %s",
                        self._model, self._fallback,
                    )
                    self._model = self._fallback
                    continue

                # Ritenta con backoff su quota (429) E su errori server temporanei
                # (503 UNAVAILABLE, 500, "overloaded", deadline...).
                if is_transient and attempt < config.GEMINI_MAX_RETRIES:
                    log.warning(
                        "Gemini errore transitorio (tentativo %s/%s), backoff %.1fs: %s",
                        attempt, config.GEMINI_MAX_RETRIES, delay, msg[:120],
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                # Retry esauriti: se è quota (anche il fallback saturo), abortiamo
                # (slitta al prossimo run); se è un 503 persistente, saltiamo il job.
                if is_quota:
                    log.error("Gemini quota esaurita (anche fallback) dopo %s tentativi.", attempt)
                    raise QuotaExhausted(msg) from exc
                log.error("Errore Gemini non recuperabile: %s", msg)
                raise
        raise QuotaExhausted("Retry esauriti.")

    # ------------------------------------------------------------------ helpers
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call
        wait = config.GEMINI_MIN_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------- module helpers
def _discard(job, reason: str) -> dict:
    return _finalize(
        job,
        {
            "score": 0,
            "language": "n/d",
            "contract_type": "n/d",
            "duration": "n/d",
            "salary": "Non menzionata",
            "skills_match": "off",
            "match_reasons": "Scartato dal pre-filtro.",
            "why_check": reason,
        },
    )


def _finalize(job, data: dict) -> dict:
    """Aggiunge i campi del job al risultato di scoring."""
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
            "source_emoji": job.source_emoji,
        }
    )
    return data


def _is_rate_limit(msg: str) -> bool:
    m = msg.lower()
    return (
        "429" in m
        or "resource_exhausted" in m
        or "quota" in m
        or "rate limit" in m
    )


def _is_server_transient(msg: str) -> bool:
    """Errori server temporanei di Gemini: vale la pena ritentare."""
    m = msg.lower()
    return (
        "503" in m
        or "500" in m
        or "unavailable" in m
        or "overloaded" in m
        or "high demand" in m
        or "deadline" in m
        or "internal error" in m
    )


def _parse_json(text: str) -> dict:
    """Estrae il JSON dalla risposta, tollerando eventuali fence ```json."""
    if not text:
        raise ValueError("Risposta Gemini vuota.")
    text = text.strip()
    # Rimuovi eventuali fence markdown.
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Ultimo tentativo: estrai il primo blocco {...}.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise

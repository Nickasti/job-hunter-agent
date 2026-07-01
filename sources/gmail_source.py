"""
sources/gmail_source.py — Fonte 1: email di LinkedIn Job Alerts via Gmail API.

Autenticazione CI-friendly: invece di un file token.json, ricostruiamo le
credenziali da CLIENT_ID + CLIENT_SECRET + REFRESH_TOKEN (tutti come env/Secret).
Il refresh token si genera UNA volta in locale con tools/generate_gmail_token.py.

Estrae i job dalle email parsando l'HTML: i link agli annunci LinkedIn hanno la
forma .../jobs/view/<id>. Da titolo/azienda/località ricaviamo un Job grezzo,
opzionalmente arricchito scaricando la pagina pubblica dell'annuncio.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

import config
from models import Job

log = logging.getLogger("sources.gmail")

_JOB_VIEW_RE = re.compile(r"/jobs/view/(\d+)")


# ----------------------------------------------------------------- auth / fetch
def _build_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=config.GMAIL_REFRESH_TOKEN,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=config.GMAIL_SCOPES,
    )
    creds.refresh(Request())  # ottiene un access token fresco
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _gmail_query(after_epoch: int | None) -> str:
    senders = " OR ".join(f"from:{s}" for s in config.LINKEDIN_SENDERS)
    query = f"({senders})"
    if after_epoch:
        query += f" after:{after_epoch}"
    return query


def fetch_jobs(db) -> list[Job]:
    """
    Scarica le nuove email LinkedIn dall'ultimo run e ne estrae i job.

    Usa db.meta['gmail_last_epoch'] come watermark temporale. Al primo run
    guarda indietro di LINKEDIN_LOOKBACK_DAYS giorni.
    """
    try:
        service = _build_service()
    except Exception as exc:  # noqa: BLE001
        log.error("Impossibile autenticarsi a Gmail: %s", exc)
        return []

    last_epoch = db.get_meta("gmail_last_epoch")
    if last_epoch:
        after = int(last_epoch)
    else:
        after = int(
            (datetime.now(timezone.utc) - timedelta(days=config.LINKEDIN_LOOKBACK_DAYS)).timestamp()
        )

    query = _gmail_query(after)
    log.info("Query Gmail: %s", query)

    try:
        msg_ids = _list_message_ids(service, query)
    except Exception as exc:  # noqa: BLE001
        log.error("Errore nel listing dei messaggi Gmail: %s", exc)
        return []

    log.info("Email LinkedIn trovate: %d", len(msg_ids))

    jobs: list[Job] = []
    newest_epoch = after
    for mid in msg_ids:
        try:
            payload = service.users().messages().get(
                userId="me", id=mid, format="full"
            ).execute()
        except Exception as exc:  # noqa: BLE001
            log.warning("Errore lettura messaggio %s: %s", mid, exc)
            continue

        internal = int(payload.get("internalDate", "0")) // 1000
        newest_epoch = max(newest_epoch, internal)

        html = _extract_html(payload)
        if not html:
            continue
        jobs.extend(_parse_linkedin_email(html))

    # Aggiorna il watermark (+1s per non rileggere l'ultima email).
    db.set_meta("gmail_last_epoch", str(newest_epoch + 1))

    # Deduplica all'interno del batch (le email LinkedIn ripetono molti job).
    jobs = _dedup(jobs)
    log.info("Job unici estratti dalle email: %d", len(jobs))

    if config.ENABLE_LINKEDIN_ENRICH:
        _enrich(jobs)
    return jobs


def _list_message_ids(service, query: str) -> list[str]:
    ids: list[str] = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=100
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


# ----------------------------------------------------------------- HTML parsing
def _extract_html(payload: dict) -> str:
    """Estrae il corpo HTML (o testo) da un messaggio Gmail (gestisce multipart)."""

    def walk(part) -> str:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/html" and data:
            return _b64(data)
        # Ricorsione sulle sottoparti.
        collected = ""
        for sub in part.get("parts", []) or []:
            collected += walk(sub)
        # Fallback: testo semplice se non c'è HTML.
        if not collected and mime == "text/plain" and data:
            return _b64(data)
        return collected

    return walk(payload.get("payload", {}))


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "replace")


def _parse_linkedin_email(html: str) -> list[Job]:
    """
    Estrae i job da un'email LinkedIn.

    Ogni annuncio compare con più anchor verso lo stesso /jobs/view/<id>
    (immagine, blocco testo, titolo). Raggruppiamo per id e per ciascun gruppo
    scegliamo il titolo pulito e il testo "contenitore" più ricco (da cui
    ricavare azienda e località). Formato tipico del blocco:
    "TITOLO AZIENDA · Città, Paese · ...".
    """
    soup = BeautifulSoup(html, "lxml")
    groups: dict[str, dict] = {}

    for a in soup.find_all("a", href=True):
        m = _JOB_VIEW_RE.search(a["href"])
        if not m:
            continue
        jid = m.group(1)
        g = groups.setdefault(jid, {"titles": [], "context": ""})
        text = _clean(a.get_text())
        if text:
            g["titles"].append(text)
        parent = a.find_parent()
        ctx = _clean(parent.get_text(" ")) if parent else ""
        if len(ctx) > len(g["context"]):
            g["context"] = ctx

    jobs: list[Job] = []
    for jid, g in groups.items():
        # Il titolo "pulito" è di solito il più corto tra i testi degli anchor.
        title = min(g["titles"], key=len) if g["titles"] else ""
        if not title and g["context"]:
            title = g["context"].split("·")[0].strip()
        if not title:
            continue
        company, location = _company_location_from(g["context"], title)
        jobs.append(
            Job(
                title=title[:200],
                company=company or "Sconosciuta",
                location=location,
                url=f"https://www.linkedin.com/jobs/view/{jid}",
                source="email",
            )
        )
    return jobs


def _company_location_from(context: str, title: str) -> tuple[str, str]:
    """
    Dal blocco "TITOLO AZIENDA · Città · ..." ricava azienda e località.
    Rimuove il titolo in testa, poi divide sui separatori.
    """
    remainder = context
    if title and context.lower().startswith(title.lower()):
        remainder = context[len(title):].strip()
    parts = [p.strip() for p in re.split(r"·|\|", remainder) if p.strip()]
    company = parts[0] if parts else ""
    location = ""
    for p in parts:
        low = p.lower()
        if any(k in low for k in ("lisbon", "lisboa", "portugal", "portogallo")):
            location = p
            break
    return company[:80], location[:80]


def _enrich(jobs: list[Job]) -> None:
    """
    Scarica la pagina pubblica di ogni annuncio LinkedIn per arricchire la
    descrizione (migliora lo scoring). Rate limit conservativo: 1 req / 5s,
    nessun login, User-Agent realistico. Rispetta i ToS sulle pagine pubbliche.
    """
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "en,it,pt"}
    for job in jobs:
        if "/jobs/view/" not in job.url:
            continue
        try:
            r = requests.get(job.url, headers=headers, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml")
                desc = soup.find("div", class_=re.compile("description__text|show-more-less-html"))
                if desc:
                    job.description = _clean(desc.get_text(" "))[:6000]
                # Località più precisa se presente.
                loc = soup.find(class_=re.compile("topcard__flavor--bullet"))
                if loc and not job.location:
                    job.location = _clean(loc.get_text())
            else:
                log.debug("LinkedIn enrich %s → HTTP %s", job.url, r.status_code)
        except requests.RequestException as exc:
            log.debug("Enrich fallito per %s: %s", job.url, exc)
        time.sleep(config.LINKEDIN_REQUEST_INTERVAL)


# ----------------------------------------------------------------- utils
def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _dedup(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        h = j.fingerprint()
        if h not in seen:
            seen.add(h)
            out.append(j)
    return out

"""
app/gmail_fetch.py — Fetch email LinkedIn per un singolo utente.

Ricostruisce le credenziali dal refresh token dell'utente (decifrato) e riusa
il parser delle email già collaudato in sources/gmail_source.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from app import config_web
from app.oauth_google import credentials_from_refresh
from models import Job
from sources.gmail_source import _extract_html, _parse_linkedin_email

log = logging.getLogger("app.gmail_fetch")


def _query(after_epoch: int) -> str:
    senders = " OR ".join(f"from:{s}" for s in config_web.LINKEDIN_SENDERS)
    q = f"({senders})"
    if after_epoch:
        q += f" after:{after_epoch}"
    return q


def fetch_new_jobs(refresh_token: str, last_epoch: int) -> tuple[list[Job], int]:
    """
    Scarica le nuove email LinkedIn dell'utente dopo `last_epoch`.
    Ritorna (lista job unici, nuovo watermark epoch).
    """
    creds = credentials_from_refresh(refresh_token)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    if last_epoch and last_epoch > 0:
        after = int(last_epoch)
    else:
        after = int(
            (datetime.now(timezone.utc) - timedelta(days=config_web.LINKEDIN_LOOKBACK_DAYS)).timestamp()
        )

    ids = _list_ids(service, _query(after))
    jobs: list[Job] = []
    newest = after
    for mid in ids:
        try:
            payload = service.users().messages().get(
                userId="me", id=mid, format="full"
            ).execute()
        except Exception as exc:  # noqa: BLE001
            log.warning("Errore lettura messaggio %s: %s", mid, exc)
            continue
        newest = max(newest, int(payload.get("internalDate", "0")) // 1000)
        html = _extract_html(payload)
        if html:
            for j in _parse_linkedin_email(html):
                j.source = "gmail"
                jobs.append(j)

    return _dedup(jobs), newest + 1


def _list_ids(service, query: str) -> list[str]:
    ids: list[str] = []
    token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, pageToken=token, maxResults=100
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids


def _dedup(jobs: list[Job]) -> list[Job]:
    seen, out = set(), []
    for j in jobs:
        h = j.fingerprint()
        if h not in seen:
            seen.add(h)
            out.append(j)
    return out

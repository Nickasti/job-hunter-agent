"""
storage/db.py — Persistenza SQLite per deduplica e cache degli score.

Su GitHub Actions il file `jobs.db` viene committato nel repo dopo ogni run,
così lo stato (job già visti, score già calcolati) sopravvive tra esecuzioni.

Tabelle:
  - jobs : un record per ogni annuncio incontrato (anche quelli scartati).
  - meta : coppie chiave/valore (es. timestamp ultimo run Gmail).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

log = logging.getLogger("storage.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_hash    TEXT PRIMARY KEY,
    url         TEXT,
    source      TEXT,
    company     TEXT,
    title       TEXT,
    location    TEXT,
    score       INTEGER,
    score_json  TEXT,
    notified    INTEGER DEFAULT 0,
    first_seen  TEXT,
    last_scored TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ dedup
    def is_known(self, job_hash: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM jobs WHERE job_hash = ?", (job_hash,))
        return cur.fetchone() is not None

    def get_cached_score(self, job_hash: str, cache_days: int) -> dict | None:
        """
        Ritorna lo score salvato se calcolato entro `cache_days` giorni,
        altrimenti None (così Gemini viene richiamato per riscorare).
        """
        cur = self.conn.execute(
            "SELECT score, score_json, last_scored FROM jobs WHERE job_hash = ?",
            (job_hash,),
        )
        row = cur.fetchone()
        if not row or not row["last_scored"] or row["score_json"] is None:
            return None
        try:
            last = datetime.fromisoformat(row["last_scored"])
        except ValueError:
            return None
        if datetime.now(timezone.utc) - last > timedelta(days=cache_days):
            return None
        try:
            return json.loads(row["score_json"])
        except json.JSONDecodeError:
            return None

    def was_notified(self, job_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT notified FROM jobs WHERE job_hash = ?", (job_hash,)
        )
        row = cur.fetchone()
        return bool(row and row["notified"])

    # ------------------------------------------------------------------ write
    def save_job(
        self,
        job,
        score: int | None = None,
        score_json: dict | None = None,
        notified: bool = False,
    ) -> None:
        """Inserisce o aggiorna un job. Preserva first_seen sugli update."""
        h = job.fingerprint()
        existing = self.conn.execute(
            "SELECT first_seen, notified FROM jobs WHERE job_hash = ?", (h,)
        ).fetchone()
        first_seen = existing["first_seen"] if existing else _now()
        # notified resta True se lo era già
        already_notified = bool(existing and existing["notified"])
        self.conn.execute(
            """
            INSERT INTO jobs
              (job_hash, url, source, company, title, location,
               score, score_json, notified, first_seen, last_scored)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_hash) DO UPDATE SET
              url=excluded.url, source=excluded.source, company=excluded.company,
              title=excluded.title, location=excluded.location,
              score=excluded.score, score_json=excluded.score_json,
              notified=excluded.notified, last_scored=excluded.last_scored
            """,
            (
                h,
                job.url,
                job.source,
                job.company,
                job.title,
                job.location,
                score,
                json.dumps(score_json, ensure_ascii=False) if score_json else None,
                1 if (notified or already_notified) else 0,
                first_seen,
                _now() if score_json is not None else None,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

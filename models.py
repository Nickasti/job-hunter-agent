"""
models.py — Strutture dati condivise tra i moduli.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


def _norm(text: str | None) -> str:
    """Normalizza una stringa per il calcolo dell'hash di deduplica."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class Job:
    """Rappresenta un annuncio di lavoro grezzo (pre-scoring)."""

    title: str
    company: str
    source: str  # "email" | "scrape"
    url: str = ""
    location: str = ""
    description: str = ""  # testo per lo scoring (può essere arricchito)

    def fingerprint(self) -> str:
        """
        Hash stabile per la deduplica.

        Preferisce l'URL (se presente e canonico); altrimenti ripiega su
        azienda + titolo. In questo modo lo stesso annuncio visto da fonti
        diverse non genera doppie notifiche.
        """
        url_key = _canonical_url(self.url)
        basis = url_key if url_key else f"{_norm(self.company)}|{_norm(self.title)}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    @property
    def source_emoji(self) -> str:
        return "📧" if self.source == "email" else "🌐"


def _canonical_url(url: str | None) -> str:
    """Rimuove query string di tracking (utm, trk, refId...) per stabilizzare l'hash."""
    if not url:
        return ""
    url = url.split("?")[0].split("#")[0].rstrip("/")
    return url.lower()

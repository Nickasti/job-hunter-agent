"""
app/top_companies.py — Aziende "top" da evidenziare nelle notifiche.

Per l'utente ADMIN (config_web.ADMIN_EMAIL), se un annuncio proviene da una di
queste aziende, la notifica Telegram viene marcata in modo vistoso (banner +
stelle + emoji). Il match è tollerante: confronto su nome normalizzato con una
lista di alias/varianti per ciascuna azienda.
"""
from __future__ import annotations

import re

# nome canonico -> lista di alias/varianti (lowercase) da cercare nel testo azienda
_TOP: dict[str, list[str]] = {
    "Microsoft": ["microsoft"],
    "Accenture": ["accenture"],
    "Google": ["google"],
    "Reply": ["reply"],
    "Amazon (AWS)": ["amazon", "aws", "amazon web services"],
    "Jakala": ["jakala"],
    "Salesforce": ["salesforce"],
    "SAS": ["sas institute", "sas "],
    "Adobe": ["adobe"],
    "Publicis Groupe": ["publicis"],
    "Deloitte": ["deloitte"],
    "EY": ["ernst & young", "ernst and young", "ernst young", "ey "],
    "PwC": ["pwc", "pricewaterhousecoopers", "pricewaterhouse"],
    "Capgemini": ["capgemini"],
    "Bain / BCG": ["bain", "boston consulting", "bcg"],
    "Intesa Sanpaolo": ["intesa sanpaolo", "intesa san paolo"],
    "Luxottica": ["luxottica", "essilorluxottica"],
    "Eni / Plenitude": ["eni ", "plenitude"],
    "Leonardo": ["leonardo s.p.a", "leonardo spa", "leonardo company", "leonardo -", "leonardo,"],
    "Synlab": ["synlab"],
    "Bending Spoons": ["bending spoons"],
    "ByteDance (TikTok)": ["bytedance", "tiktok"],
    "Meta": ["meta platforms", "meta,", "facebook"],
    "IBM": ["ibm", "international business machines"],
    "Alkemy": ["alkemy"],
}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def match_top_company(company: str | None, title: str = "", description: str = "") -> str | None:
    """
    Ritorna il nome canonico dell'azienda top se l'annuncio la riguarda,
    altrimenti None. Cerca soprattutto nel campo azienda; come fallback usa il
    titolo/descrizione (a volte l'azienda è citata lì).
    """
    hay_company = " " + _norm(company) + " "
    hay_all = " " + _norm(f"{company} {title} {description}") + " "
    for canonical, aliases in _TOP.items():
        for alias in aliases:
            a = alias if alias.endswith(" ") else alias
            # match sul campo azienda (più affidabile) o, per nomi non ambigui,
            # anche nel testo generale.
            if a in hay_company:
                return canonical
    # secondo giro: nomi lunghi/non ambigui anche nel testo generale
    for canonical, aliases in _TOP.items():
        for alias in aliases:
            if len(alias.strip()) >= 6 and alias in hay_all:
                return canonical
    return None

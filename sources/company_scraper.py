"""
sources/company_scraper.py — Fonte 2: scraping delle career page aziendali.

Tre strategie, scelte per azienda in companies.yaml:
  - "api"     : ATS con API pubblica e affidabile (Greenhouse, Lever).
  - "static"  : pagina HTML server-side → requests + BeautifulSoup.
  - "dynamic" : pagina JS-heavy (SPA, Workday...) → Playwright headless.

Filtri lato scraping (per ridurre il lavoro a valle):
  - location_filter : tiene solo i job con località coerente (Lisbon/Lisboa/Portugal).
  - keyword_filter  : tiene solo i job il cui titolo contiene una keyword utile.

Vincoli: rispetto di robots.txt (config.RESPECT_ROBOTS), User-Agent realistico,
gestione errori per azienda (un fallimento non blocca le altre).
"""
from __future__ import annotations

import logging
import re
import urllib.robotparser as robotparser
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

import config
from models import Job
from sources.browser_scraper import HeadlessBrowser, JobTitleParser

log = logging.getLogger("sources.scraper")

_robots_cache: dict[str, robotparser.RobotFileParser] = {}
_parser = JobTitleParser()


# ----------------------------------------------------------------- entry point
def fetch_jobs(companies_path: str = None) -> list[Job]:
    companies_path = companies_path or config.COMPANIES_PATH
    try:
        with open(companies_path, "r", encoding="utf-8") as f:
            companies = yaml.safe_load(f) or []
    except FileNotFoundError:
        log.error("companies.yaml non trovato: %s", companies_path)
        return []

    enabled = [c for c in companies if c.get("enabled", True)]
    needs_browser = config.ENABLE_PLAYWRIGHT and any(
        (c.get("strategy") or "").lower() == "dynamic" for c in enabled
    )

    all_jobs: list[Job] = []
    browser: HeadlessBrowser | None = None
    try:
        if needs_browser:
            try:
                browser = HeadlessBrowser()
                browser.start()
            except RuntimeError as exc:
                log.error("%s — le aziende 'dynamic' verranno saltate.", exc)
                browser = None
        for company in enabled:
            name = company.get("name", "?")
            try:
                jobs = _scrape_company(company, browser)
                log.info("[%s] %d job pertinenti", name, len(jobs))
                all_jobs.extend(jobs)
            except Exception as exc:  # noqa: BLE001 — isolamento per azienda
                log.warning("[%s] scraping fallito: %s", name, exc)
    finally:
        if browser:
            browser.close()
    return all_jobs


def _scrape_company(company: dict, browser: HeadlessBrowser | None = None) -> list[Job]:
    strategy = (company.get("strategy") or "static").lower()
    if strategy == "api":
        raw = _scrape_api(company)
    elif strategy == "dynamic":
        raw = _scrape_dynamic(company, browser)
    else:
        raw = _scrape_static(company)
    return _postfilter(raw, company)


# --------------------------------------------------------------------- API ATS
def _scrape_api(company: dict) -> list[Job]:
    api_type = (company.get("api_type") or "").lower()
    token = company.get("api_token")
    name = company.get("name", "?")
    if not token:
        log.warning("[%s] strategy=api ma manca api_token", name)
        return []

    if api_type == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        data = _get_json(url)
        jobs = []
        for j in (data or {}).get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            desc = _strip_html(j.get("content", ""))
            jobs.append(
                Job(
                    title=j.get("title", ""),
                    company=name,
                    location=loc,
                    url=j.get("absolute_url", ""),
                    description=desc,
                    source="scrape",
                )
            )
        return jobs

    if api_type == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        data = _get_json(url)
        jobs = []
        for j in data or []:
            cats = j.get("categories", {}) or {}
            jobs.append(
                Job(
                    title=j.get("text", ""),
                    company=name,
                    location=cats.get("location", ""),
                    url=j.get("hostedUrl", ""),
                    description=_strip_html(j.get("descriptionPlain") or j.get("description", "")),
                    source="scrape",
                )
            )
        return jobs

    log.warning("[%s] api_type non supportato: %s", name, api_type)
    return []


# ------------------------------------------------------------------ static HTML
def _scrape_static(company: dict) -> list[Job]:
    url = company.get("career_page_url")
    name = company.get("name", "?")
    if not url or not _robots_ok(url):
        return []
    html = _get_html(url)
    if not html:
        return []
    return _parse_listing_html(html, url, company)


# ---------------------------------------------------------------- dynamic (JS)
def _scrape_dynamic(company: dict, browser: HeadlessBrowser | None) -> list[Job]:
    url = company.get("career_page_url")
    name = company.get("name", "?")
    if not url:
        return []
    if browser is None:
        log.info("[%s] strategy=dynamic ma browser non disponibile; salto.", name)
        return []
    html = browser.fetch(url, wait_selector=company.get("selector"))
    if not html:
        return []
    return _parse_listing_html(html, url, company)


# ------------------------------------------------------------------ HTML parser
def _parse_listing_html(html: str, base_url: str, company: dict) -> list[Job]:
    """Delegato a JobTitleParser; qui solo la mappatura verso il modello Job."""
    name = company.get("name", "?")
    postings = _parser.extract(html, base_url, selector=company.get("selector"))
    return [
        Job(
            title=p.title,
            company=name,
            location=p.location,
            url=p.url,
            description=p.title,  # arricchito a valle solo se necessario
            source="scrape",
        )
        for p in postings
    ]


# ------------------------------------------------------------------ post filter
def _postfilter(jobs: list[Job], company: dict) -> list[Job]:
    loc_filters = [s.lower() for s in (company.get("location_filter") or [])]
    kw_filters = [s.lower() for s in (company.get("keyword_filter") or [])]

    out = []
    for j in jobs:
        blob = f"{j.title} {j.location} {j.description}".lower()
        if loc_filters and not any(f in blob for f in loc_filters):
            continue
        if kw_filters and not any(f in j.title.lower() for f in kw_filters):
            continue
        out.append(j)
    return out


# ------------------------------------------------------------------ http utils
def _robots_ok(url: str) -> bool:
    if not config.RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(base, "/robots.txt"))
        try:
            rp.read()
        except Exception:  # noqa: BLE001 — se robots non leggibile, sii permissivo
            rp = None
        _robots_cache[base] = rp
    if rp is None:
        return True
    allowed = rp.can_fetch(config.USER_AGENT, url)
    if not allowed:
        log.info("robots.txt vieta %s — salto.", url)
    return allowed


def _get_html(url: str) -> str | None:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en,pt,it"},
            timeout=config.HTTP_TIMEOUT,
        )
        if r.status_code == 200:
            return r.text
        log.debug("GET %s → HTTP %s", url, r.status_code)
    except requests.RequestException as exc:
        log.debug("GET %s fallito: %s", url, exc)
    return None


def _get_json(url: str):
    try:
        r = requests.get(
            url, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        log.debug("GET(json) %s → HTTP %s", url, r.status_code)
    except (requests.RequestException, ValueError) as exc:
        log.debug("GET(json) %s fallito: %s", url, exc)
    return None


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return _clean(BeautifulSoup(html, "lxml").get_text(" "))[:6000]


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

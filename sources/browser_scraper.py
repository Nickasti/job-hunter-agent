"""
sources/browser_scraper.py — Automazione browser "educata" per career page pubbliche.

Due componenti riusabili:

  HeadlessBrowser
      Gestisce UN solo browser Chromium headless per tutta la sessione di
      scraping (invece di lanciarne uno per azienda). Applica:
        - rispetto di robots.txt (config.RESPECT_ROBOTS);
        - rate-limit per dominio: minimo config.SCRAPE_MIN_INTERVAL secondi
          tra due richieste allo stesso host, con jitter casuale;
        - User-Agent realistico, locale e viewport coerenti;
        - blocco di immagini/font/media per ridurre banda e carico sul server.

  JobTitleParser
      Parser generico: HTML + selettore CSS opzionale → lista di
      {"title", "url", "location"}. Se il selettore manca o non trova nulla,
      ripiega sugli anchor con href "job-like".

Uso tipico:

    with HeadlessBrowser() as browser:
        html = browser.fetch(url, wait_selector="a[href*='/job/']")
        postings = JobTitleParser().extract(html, base_url=url,
                                            selector="a[href*='/job/']")
"""
from __future__ import annotations

import logging
import random
import re
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config

log = logging.getLogger("sources.browser")

# Pattern href che identificano un link a un annuncio di lavoro.
_JOB_HREF_TOKENS = (
    "/job", "/jobs/", "/careers/", "/vagas/", "/position",
    "/opening", "gh_jid", "/o/", "jobdetail", "requisition",
)


@dataclass
class JobPosting:
    """Risultato grezzo del parser: solo ciò che si legge dal listato."""
    title: str
    url: str
    location: str = ""


# =========================================================== HeadlessBrowser
class HeadlessBrowser:
    """
    Browser headless condiviso, con rate-limit per dominio e robots.txt.

    Usarlo come context manager garantisce la chiusura del browser anche in
    caso di eccezioni. Ogni fetch apre una pagina nuova (stato pulito) ma
    riusa lo stesso processo browser.
    """

    def __init__(
        self,
        min_interval: float | None = None,
        timeout_ms: int = 45_000,
        block_heavy_resources: bool = True,
    ):
        self.min_interval = (
            min_interval if min_interval is not None else config.SCRAPE_MIN_INTERVAL
        )
        self.timeout_ms = timeout_ms
        self.block_heavy_resources = block_heavy_resources
        self._pw = None
        self._browser = None
        self._context = None
        self._last_hit: dict[str, float] = {}  # host → timestamp ultima richiesta
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    # ------------------------------------------------------------- lifecycle
    def __enter__(self) -> "HeadlessBrowser":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright non installato: pip install playwright && playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=config.USER_AGENT,
            locale="it-IT",
            viewport={"width": 1366, "height": 900},
        )
        if self.block_heavy_resources:
            self._context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "font", "media")
                else route.continue_(),
            )

    def close(self) -> None:
        for obj in (self._context, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001 — chiusura best-effort
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._context = self._browser = self._pw = None

    # ----------------------------------------------------------------- fetch
    def fetch(self, url: str, wait_selector: str | None = None) -> str | None:
        """
        Naviga alla URL e ritorna l'HTML del DOM renderizzato.
        Ritorna None se robots.txt vieta l'accesso o in caso di errore.
        """
        if self._context is None:
            raise RuntimeError("Browser non avviato: usa 'with HeadlessBrowser() as b:'")
        if not self._robots_ok(url):
            return None
        self._throttle(url)

        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            try:
                if wait_selector:
                    page.wait_for_selector(wait_selector, timeout=15_000)
                else:
                    page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001 — proseguiamo col DOM disponibile
                pass
            return page.content()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch %s fallito: %s", url, exc)
            return None
        finally:
            page.close()

    # ------------------------------------------------------------- cortesia
    def _throttle(self, url: str) -> None:
        """Attende finché non è passato min_interval (+jitter) dall'ultima
        richiesta allo stesso host. Host diversi non si bloccano a vicenda."""
        host = urlparse(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval + random.uniform(0.5, 2.5) - (time.time() - last)
            if wait > 0:
                log.debug("throttle %s: attendo %.1fs", host, wait)
                time.sleep(wait)
        self._last_hit[host] = time.time()

    def _robots_ok(self, url: str) -> bool:
        if not config.RESPECT_ROBOTS:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            try:
                rp.read()
            except Exception:  # noqa: BLE001 — robots illeggibile → permissivo
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        if rp is None:
            return True
        allowed = rp.can_fetch(config.USER_AGENT, url)
        if not allowed:
            log.info("robots.txt vieta %s — salto.", url)
        return allowed


# ============================================================ JobTitleParser
class JobTitleParser:
    """
    Estrae i titoli delle posizioni da un listato HTML.

    extract(html, base_url, selector=None) → list[JobPosting]
      - con `selector`: ogni elemento selezionato è una card/anchor di job;
      - senza (o se il selettore non trova nulla): fallback su tutti gli
        anchor con href che "sembra" un annuncio.
    """

    def extract(
        self, html: str, base_url: str, selector: str | None = None
    ) -> list[JobPosting]:
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")

        candidates = soup.select(selector) if selector else []
        used_selector = bool(candidates)
        if not candidates:
            candidates = soup.find_all("a", href=True)

        postings: list[JobPosting] = []
        seen: set[str] = set()
        for el in candidates:
            anchor = el if el.name == "a" and el.get("href") else el.find("a", href=True)
            if not anchor:
                continue
            href = anchor.get("href", "")
            if not self._looks_like_job_link(href):
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            title = self._clean(el.get_text(" ") if used_selector else anchor.get_text(" "))
            if not title:
                continue
            postings.append(
                JobPosting(
                    title=title[:200],
                    url=full_url,
                    location=self._guess_location(el),
                )
            )
        return postings

    # ----------------------------------------------------------- heuristics
    @staticmethod
    def _looks_like_job_link(href: str) -> bool:
        h = href.lower()
        return any(tok in h for tok in _JOB_HREF_TOKENS)

    @staticmethod
    def _guess_location(el) -> str:
        text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
        for kw in ("Lisbon", "Lisboa", "Portugal", "Milano", "Milan", "Roma", "Italy", "Italia", "Remote"):
            if kw.lower() in text.lower():
                return kw
        return ""

    @staticmethod
    def _clean(text: str | None) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

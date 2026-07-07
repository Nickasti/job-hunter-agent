"""
app/main.py — Applicazione FastAPI della piattaforma job-hunter multi-utente.

Rotte principali:
  Auth        : /register, /login, /logout
  Onboarding  : /onboarding, /auth/google/*, /onboarding/telegram*, /onboarding/criteria
  Dashboard   : /dashboard, /dashboard/toggle, /dashboard/criteria
  Telegram    : /telegram/webhook (pubblica), /telegram/poll, /telegram/set-webhook (admin)
  Esecuzione  : /api/run-cycle (bearer token) — chiamata dal cron GitHub Actions
  Utility     : /healthz
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import config_web, crypto, geo, oauth_google, telegram_bot
from app.auth import (
    authenticate,
    create_user,
    get_current_user,
    get_user_by_email,
    login_session,
    logout_session,
)
from app.cycle import run_cycle
from app.db import get_session, init_db
from app.models_db import RunLog, UserCriteria, UserGoogleToken, UserJob, UserMatch, UserTelegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("app.main")

app = FastAPI(title="VeredAI platform")
app.add_middleware(SessionMiddleware, secret_key=config_web.SESSION_SECRET, https_only=False)
templates = Jinja2Templates(directory=str(config_web.BASE_DIR / "app" / "templates"))


@app.on_event("startup")
def _startup():
    init_db()
    missing = config_web.missing_required()
    if missing:
        log.warning("Variabili mancanti (alcune funzioni non attive): %s", ", ".join(missing))


# ============================================================ helper
def _require_login(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        return None
    return user


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _split_csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _criteria_ctx(criteria) -> dict:
    """Variabili per i menù a tendina dei criteri (lingue + Stati/città)."""
    return {
        "languages": geo.LANGUAGES,
        "europe": geo.frontend(),
        "country_choices": geo.country_choices(),
        "sel_languages": _split_csv(getattr(criteria, "lingua_pref", "")),
        "sel_countries": _split_csv(getattr(criteria, "countries", "")),
        "sel_cities": _split_csv(getattr(criteria, "cities", "")),
        "sel_cities_custom": getattr(criteria, "cities_custom", "") or "",
    }


# ============================================================ root / auth
def _render_hero(request: Request, db: Session):
    """Landing pubblica (hero). Visibile a tutti; i pulsanti si adattano al login."""
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request, "onboarding.html", {"request": request, "logged_in": user is not None}
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_session)):
    return _render_hero(request, db)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(request, "register.html", {"request": request, "error": None})


@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    email = email.strip().lower()
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "register.html", {"error": "Password troppo corta (min 8)."}
        )
    if get_user_by_email(db, email):
        return templates.TemplateResponse(
            request, "register.html", {"error": "Email già registrata."}
        )
    user = create_user(db, email, password)
    login_session(request, user)
    return _redirect("/onboarding/setup")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_session),
):
    user = authenticate(db, email, password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Credenziali non valide."}
        )
    login_session(request, user)
    return _redirect("/dashboard")


@app.post("/logout")
def logout(request: Request):
    logout_session(request)
    return _redirect("/login")


# ============================================================ onboarding
@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request, db: Session = Depends(get_session)):
    # Alias pubblico della landing (stessa hero della root).
    return _render_hero(request, db)


@app.get("/onboarding/setup", response_class=HTMLResponse)
def onboarding_setup(request: Request, db: Session = Depends(get_session)):
    """Pagina di configurazione (i passi), raggiunta dal pulsante 'Inizia ora'."""
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "request": request,
            "user": user,
            "google_connected": user.google is not None,
            "telegram_linked": bool(user.telegram and user.telegram.chat_id),
            "deep_link": telegram_bot.deep_link(user.telegram.link_code) if user.telegram else "#",
            "criteria": user.criteria,
            **_criteria_ctx(user.criteria),
        },
    )


# ------------------------------------------------ Google OAuth
@app.get("/auth/google/start")
def google_start(request: Request, db: Session = Depends(get_session)):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")
    state = secrets.token_urlsafe(24)
    url, code_verifier = oauth_google.authorization_url(state)
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier
    return _redirect(url)


@app.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_session),
):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")
    if not code or state != request.session.get("oauth_state"):
        raise HTTPException(status_code=400, detail="OAuth state non valido.")

    creds = oauth_google.exchange_code(
        code, state=state, code_verifier=request.session.get("oauth_code_verifier")
    )
    if not creds.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Nessun refresh token ricevuto. Revoca l'accesso da account Google e riprova.",
        )

    enc = crypto.encrypt(creds.refresh_token)
    existing = db.get(UserGoogleToken, user.id)
    if existing:
        existing.refresh_token_enc = enc
        existing.scopes = " ".join(creds.scopes or config_web.GOOGLE_SCOPES)
        existing.connected_at = datetime.now(timezone.utc)
    else:
        db.add(
            UserGoogleToken(
                user_id=user.id,
                refresh_token_enc=enc,
                scopes=" ".join(creds.scopes or config_web.GOOGLE_SCOPES),
            )
        )
    db.commit()
    return _redirect("/onboarding/setup")


# ------------------------------------------------ Telegram link
@app.get("/onboarding/telegram/status", response_class=HTMLResponse)
def telegram_status(request: Request, db: Session = Depends(get_session)):
    """Frammento HTMX: mostra se il Telegram è collegato (polling dalla pagina)."""
    user = _require_login(request, db)
    if not user:
        return HTMLResponse("<span>non loggato</span>")
    linked = bool(user.telegram and user.telegram.chat_id)
    if linked:
        return HTMLResponse('<span class="ok">✅ Telegram collegato</span>')
    return HTMLResponse('<span class="pending">⏳ In attesa del tuo /start sul bot…</span>')


# ------------------------------------------------ Criteri
def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.post("/onboarding/criteria")
@app.post("/dashboard/criteria")
async def save_criteria(request: Request, db: Session = Depends(get_session)):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")

    # Lettura diadretta del form: getlist() gestisce i campi multi-valore
    # (menù a tendina a selezione multipla) in modo affidabile.
    form = await request.form()
    languages = form.getlist("languages")
    countries = form.getlist("countries")
    cities = form.getlist("cities")

    # Validazione contro gli elenchi controllati (niente valori arbitrari)
    valid_langs = [l for l in languages if l in geo.LANGUAGES]
    valid_codes = [x for x in countries if x in geo.valid_country_codes()]
    city_ids = geo.valid_city_ids()
    valid_cities = [x for x in cities if x in city_ids]

    # Città scritte a mano (non in elenco): CSV libero.
    custom_list = [x.strip() for x in (form.get("cities_custom") or "").split(",") if x.strip()]

    c: UserCriteria = user.criteria or UserCriteria(user_id=user.id)
    c.lingua_pref = ",".join(valid_langs)
    c.countries = ",".join(valid_codes)
    c.cities = ",".join(valid_cities)
    c.cities_custom = ", ".join(custom_list)
    # location_filter = sinonimi espansi (EN/IT/locale) + città a mano, per lo scoring
    expanded = geo.expand(valid_codes, valid_cities) + custom_list
    c.location_filter = ",".join(dict.fromkeys(expanded))  # dedup, ordine preservato
    c.contratto_pref = (form.get("contratto_pref") or "").strip()
    c.skills_keywords = (form.get("skills_keywords") or "").strip()
    c.salario_minimo = max(0, _to_int(form.get("salario_minimo"), 0))
    c.durata_minima = max(0, _to_int(form.get("durata_minima"), 0))
    c.soglia_notifica = max(0, min(100, _to_int(form.get("soglia_notifica"), 55)))
    db.add(c)
    # I criteri sono cambiati: azzera le valutazioni già fatte, così i job
    # verranno RI-valutati col nuovo filtro al prossimo ciclo (niente risultati
    # "congelati" sotto criteri vecchi).
    db.query(UserMatch).filter(UserMatch.user_id == user.id).delete()
    db.commit()
    dest = "/dashboard" if request.url.path.startswith("/dashboard") else "/onboarding/setup"
    return _redirect(dest)


@app.post("/onboarding/activate")
def activate(request: Request, db: Session = Depends(get_session)):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")
    user.is_active = True
    db.commit()
    return _redirect("/dashboard")


# ============================================================ dashboard
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_session)):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")

    # Mostra solo le offerte pertinenti: score > 0 esclude quelle scartate dal
    # pre-filtro (località/senior sbagliati), che avrebbero score 0.
    matches = db.execute(
        select(UserMatch, UserJob)
        .join(UserJob, UserMatch.job_id == UserJob.id)
        .where(UserMatch.user_id == user.id, UserMatch.score > 0)
        .order_by(UserMatch.score.desc(), UserMatch.scored_at.desc())
        .limit(100)
    ).all()
    rows = []
    for m, j in matches:
        try:
            detail = json.loads(m.dettaglio_score) if m.dettaglio_score else {}
        except json.JSONDecodeError:
            detail = {}
        rows.append({"match": m, "job": j, "detail": detail})

    logs = db.scalars(select(RunLog).order_by(RunLog.started_at.desc()).limit(10)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "google_connected": user.google is not None,
            "telegram_linked": bool(user.telegram and user.telegram.chat_id),
            "criteria": user.criteria,
            "rows": rows,
            "logs": logs,
            **_criteria_ctx(user.criteria),
        },
    )


@app.post("/dashboard/toggle")
def toggle_active(request: Request, db: Session = Depends(get_session)):
    user = _require_login(request, db)
    if not user:
        return _redirect("/login")
    user.is_active = not user.is_active
    db.commit()
    return _redirect("/dashboard")


# ============================================================ Telegram webhook
@app.post(config_web.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_session),
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if x_telegram_bot_api_secret_token != config_web.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="webhook secret non valido")
    update = await request.json()
    _process_telegram_update(update, db)
    return JSONResponse({"ok": True})


def _process_telegram_update(update: dict, db: Session) -> bool:
    parsed = telegram_bot.extract_start_code(update)
    if not parsed:
        return False
    chat_id, code = parsed
    ut = db.scalar(select(UserTelegram).where(UserTelegram.link_code == code))
    if not ut:
        telegram_bot.send_message(chat_id, "Codice non riconosciuto\\. Riprova dal sito\\.")
        return False
    ut.chat_id = str(chat_id)
    ut.linked_at = datetime.now(timezone.utc)
    db.commit()
    telegram_bot.send_message(
        chat_id, "✅ Account collegato\\! Riceverai qui le offerte in target\\."
    )
    return True


@app.post("/telegram/poll")
def telegram_poll(
    request: Request,
    authorization: str = Header(default=""),
    db: Session = Depends(get_session),
):
    """Fallback per test locale senza webhook: processa gli update in coda."""
    _check_bearer(authorization)
    updates = telegram_bot.get_updates()
    linked = 0
    last = None
    for u in updates:
        last = u.get("update_id")
        if _process_telegram_update(u, db):
            linked += 1
    # Conferma gli update processati.
    if last is not None:
        telegram_bot.get_updates(offset=last + 1)
    return {"processed": len(updates), "linked": linked}


@app.post("/telegram/set-webhook")
def telegram_set_webhook(authorization: str = Header(default="")):
    _check_bearer(authorization)
    return telegram_bot.set_webhook() or {"ok": False}


# ============================================================ run-cycle
def _check_bearer(authorization: str):
    expected = f"Bearer {config_web.RUN_CYCLE_TOKEN}"
    if not config_web.RUN_CYCLE_TOKEN or authorization != expected:
        raise HTTPException(status_code=401, detail="bearer token non valido")


@app.post("/api/run-cycle")
def api_run_cycle(authorization: str = Header(default="")):
    _check_bearer(authorization)
    try:
        stats = run_cycle()
        return {"ok": True, "stats": stats}
    except Exception as exc:  # noqa: BLE001
        log.exception("run-cycle fallito")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/healthz")
def healthz():
    return {"ok": True}

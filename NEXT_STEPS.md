# 🧭 NEXT STEPS — Stato del progetto e cosa manca

> ⚠️ Questo file NON contiene segreti (il repo è pubblico). I valori sensibili
> (chiavi, token, `DATABASE_URL`) stanno solo nel `.env` locale e nelle env var
> dell'hosting. Qui c'è solo *cosa* fare, non i valori.

## Cos'è il progetto

Agente che notifica su **Telegram** offerte di **stage a Lisbona** pertinenti al
profilo, valutandole con **Gemini**. Esiste in due forme nello stesso repo:

- **Single-user** (`main.py`, `companies.yaml`, `sources/`, `storage/`): la versione
  originale, gira per un solo utente.
- **Multi-utente** (`app/`): piattaforma web FastAPI dove più persone si registrano,
  collegano il proprio Gmail/Telegram e impostano i propri criteri. ← *versione in corso di deploy*

---

## ✅ FATTO

### Agente single-user (già live in passato)
- [x] Lettura email LinkedIn via Gmail API, scoring Gemini, notifiche Telegram
- [x] Deploy su GitHub Actions (cron orario) — poi sostituito dal cron della piattaforma
- [x] Scraping career page (29 aziende): **fuori scope ora**, file lasciati nel repo inutilizzati

### Piattaforma multi-utente (`app/`) — costruita e testata
- [x] Schema DB (utenti, token Google cifrati, Telegram, criteri, job, match, log)
- [x] Auth email+password (bcrypt) + sessioni cookie firmate
- [x] Cifratura dei refresh token at-rest (Fernet / `MASTER_KEY`)
- [x] OAuth Google **condiviso** (un solo client) + fix PKCE — **testato in locale, funziona**
- [x] Bot Telegram **condiviso** con deep-link/webhook + `/telegram/poll` di fallback
- [x] Onboarding wizard + Dashboard (criteri, stato connessioni, match, log)
- [x] Scoring **parametrico** per-utente con budget Gemini **globale** per ciclo
- [x] `POST /api/run-cycle` (protetto da bearer token)
- [x] Workflow GitHub Actions ridotto a sola "sveglia" (curl all'endpoint)
- [x] Test end-to-end (`test_platform.py`): due utenti, criteri diversi, notifiche diverse ✔

### Deploy — passi già completati
- [x] **Neon**: database Postgres creato, tabelle generate, connessione verificata
- [x] **Google**: client OAuth "Web application" creato, redirect URI localhost + Render
- [x] OAuth testato in locale → **"Google collegato"** ✅

---

## ⏳ DA FARE (per andare live)

### PASSO 3 — Render ✅ COMPLETATO
- [x] Account Render creato, Blueprint applicato, env var inserite
- [x] App live su **https://job-hunter-platform.onrender.com** (healthz ok)
- [x] `POST /api/run-cycle` verificato con bearer token (ok:true, DB Neon raggiunto)

### PASSO 4 — Finalizzazione ✅ COMPLETATO
- [x] `PUBLIC_BASE_URL` impostato su Render (`https://job-hunter-platform.onrender.com`)
- [x] Redirect URI Google già registrato correttamente
- [x] Webhook Telegram registrato e verificato (getWebhookInfo: nessun errore)
      (fix: TELEGRAM_WEBHOOK_SECRET sanitizzato al charset ammesso da Telegram)

### PASSO 5 — Cron su GitHub Actions ✅ COMPLETATO
- [x] Secret `RUN_CYCLE_URL` e `RUN_CYCLE_TOKEN` impostati nel repo
- [x] Workflow `job-hunter-cron` riattivato
- [x] Run di prova: **success** (7s) — il ciclo orario è operativo

### PASSO 6 — Collaudo con utenti reali
- [ ] Aggiungere le email dei 2-3 tester come **Utenti di test** in Google Cloud
- [ ] Ogni tester: Registrati → Connetti Gmail → Avvia il bot Telegram → Criteri → Attiva
- [ ] Verificare che arrivino notifiche personalizzate e che la dashboard mostri i match
- [ ] Controllare un run reale: `Actions → job-hunter-cron → Run workflow` (o attendere il cron orario)

### PASSO 7 — Grafica / UI (in corso)
- [x] **Onboarding** (`/onboarding`): rifatta con hero video a schermo intero, fade JS,
      titolo "Find Your Path / Find Your Job", sottotitolo Agentic AI, pulsante "Inizia ora".
- [ ] **DA SISTEMARE — tutta la parte grafica successiva all'onboarding**, ancora nel
      vecchio stile scuro/base:
  - [ ] Pagina **configurazione** (`/onboarding/setup`): allineare lo stile alla hero
        (font, spaziature, coerenza col resto). Ora è un layout chiaro "base", da rifinire.
  - [ ] **Dashboard** (`/dashboard`): ancora tema scuro `base.html` — da ridisegnare
        (stato agente, criteri, lista offerte con breakdown, tabella esecuzioni).
  - [ ] **Login / Registrazione** (`/login`, `/register`): ancora tema scuro `base.html`,
        da adeguare al nuovo look.
  - [ ] Rifinire testi/branding: **logo** ("Logoipsum" → nome piattaforma), bottoni nav
        ("Dashboard" / "Log In" che fa logout — scritte da adattare), stile pulsanti.
  - [ ] (Opzionale) Video hero a risoluzione più alta o upscale AI (a crediti) se si
        vuole più nitidezza del file sorgente attuale.

---

## 📌 Note operative
- Repo **pubblico** su GitHub (minuti Actions illimitati); nessun segreto committato.
- Render free "dorme" dopo inattività: il cron orario lo risveglia (curl con retry).
- Quota Gemini free condivisa tra utenti: gestita con budget/throttling/cache.
- Se si modifica il codice in locale: `git pull` prima di editare.
- Guida deploy dettagliata: [README_PLATFORM.md](README_PLATFORM.md).
- Server locale di prova: `uvicorn app.main:app --reload` → http://localhost:8000
  (usa sempre `localhost`, non `127.0.0.1`, per l'OAuth).

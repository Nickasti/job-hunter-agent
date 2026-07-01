# 🌐 Job Hunter — Piattaforma web multi-utente

Versione multi-utente dell'agente: ogni persona si registra, collega **il proprio
Gmail e Telegram**, imposta **i propri criteri**, e riceve notifiche personalizzate.
Pensata per un test con 2-3 persone.

> ℹ️ La versione **single-user** (script `main.py` + `companies.yaml` +
> `sources/company_scraper.py`) resta nel repo, **inutilizzata**, pronta per
> reintrodurre lo scraping in futuro. Vedi [README.md](README.md).

## Architettura

```
Utente ──browser──▶ App web FastAPI (Render, free) ──▶ Postgres (Neon, free)
                         │  OAuth Gmail condiviso · Bot Telegram condiviso · Gemini
GitHub Actions (cron orario) ──POST /api/run-cycle (Bearer)──▶ App web
```

- **Gmail**: un solo progetto Google Cloud + un OAuth client **condiviso**. L'utente
  clicca "Connetti Gmail" → consent screen → salviamo il suo refresh token **cifrato**.
- **Telegram**: un solo bot. Deep-link `t.me/<bot>?start=<codice>` → l'utente preme
  Avvia → il webhook associa il suo `chat_id`. Zero setup lato utente.
- **DB**: Postgres persistente (Neon). Segreti (refresh token) **cifrati at-rest**
  con Fernet (`MASTER_KEY`). Niente SQLite committato in git.
- **Scheduler**: GitHub Actions è solo la "sveglia": chiama `POST /api/run-cycle`.
- **Gemini**: budget/throttling **globali per ciclo** (una sola istanza scorer).

---

## 1) Sviluppo locale

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements-web.txt

# .env: copia da .env.example e compila almeno MASTER_KEY, SESSION_SECRET,
# GOOGLE_CLIENT_ID/SECRET, TELEGRAM_BOT_TOKEN/USERNAME, GEMINI_API_KEY, RUN_CYCLE_TOKEN
uvicorn app.main:app --reload
# App su http://localhost:8000  (DB SQLite in ./data/app.db)
```

Test end-to-end offline (mock Gemini/Telegram):
```bash
python test_platform.py
```

Per l'OAuth in locale Google richiede HTTPS: usa un tunnel (ngrok) e imposta
`PUBLIC_BASE_URL` all'URL https del tunnel, registrandolo come redirect URI.

---

## 2) Postgres gratuito (Neon)

1. Crea account su <https://neon.tech> → **New Project**.
2. Copia la connection string e adattala al driver psycopg v3:
   ```
   postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require
   ```
3. Sarà la env var `DATABASE_URL`. Le tabelle si creano da sole all'avvio.

---

## 3) Google OAuth condiviso (client "Web application")

Nel progetto Google Cloud (Gmail API già abilitata):

1. **Credenziali → Crea credenziali → ID client OAuth → Applicazione web**.
2. **URI di reindirizzamento autorizzati**: aggiungi
   `https://<tuo-dominio-render>/auth/google/callback`
   (e, per i test locali con ngrok, l'equivalente https del tunnel).
3. Copia **Client ID** e **Client secret** → env `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
4. **Schermata consenso OAuth → Utenti di test**: aggiungi le email delle 2-3
   persone del test (scope `gmail.readonly` è sensibile: in modalità *Testing*
   solo i test user possono autorizzare — max 100).

---

## 4) Bot Telegram condiviso

1. Da @BotFather crea (o riusa) un bot → copia il **token** → `TELEGRAM_BOT_TOKEN`.
2. Imposta `TELEGRAM_BOT_USERNAME` = username del bot **senza @**.
3. Dopo il deploy, registra il webhook una volta:
   ```bash
   curl -X POST https://<dominio-render>/telegram/set-webhook \
        -H "Authorization: Bearer <RUN_CYCLE_TOKEN>"
   ```
   (In locale senza webhook usa invece `POST /telegram/poll` con lo stesso Bearer.)

---

## 5) Deploy su Render

1. <https://render.com> → **New → Blueprint** → seleziona questo repo (usa `render.yaml`).
2. Render crea il web service `job-hunter-platform`. Compila le env `sync:false`
   nella dashboard: `DATABASE_URL`, `MASTER_KEY`, `RUN_CYCLE_TOKEN`,
   `GOOGLE_CLIENT_ID/SECRET`, `TELEGRAM_BOT_TOKEN/USERNAME`, `GEMINI_API_KEY`.
   - Genera `MASTER_KEY`:
     `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`
3. Primo deploy → ottieni l'URL pubblico (es. `https://job-hunter-platform.onrender.com`).
4. Imposta `PUBLIC_BASE_URL` con quell'URL e **redeploy**.
5. Aggiungi il redirect URI Google (punto 3.2) con lo stesso dominio, poi registra
   il webhook Telegram (punto 4.3).

> Render free "dorme" dopo inattività: il cron orario lo risveglia (il workflow
> usa `--retry` e `--max-time 180` per tollerare il cold start).

---

## 6) Cron via GitHub Actions

Nel repo GitHub → **Settings → Secrets and variables → Actions**:

| Secret | Valore |
|---|---|
| `RUN_CYCLE_URL` | `https://<dominio-render>/api/run-cycle` |
| `RUN_CYCLE_TOKEN` | stesso valore della env `RUN_CYCLE_TOKEN` su Render |

Il workflow [.github/workflows/run-agent.yml](.github/workflows/run-agent.yml) ogni
ora fa solo `curl` verso l'endpoint. Nessuna logica applicativa nel YAML.

---

## Onboarding di un nuovo utente (test)

1. Aggiungi la sua email tra i **test user** in Google Cloud (punto 3.4).
2. Gli mandi il link dell'app. Lui: **Registrati → Connetti Gmail → Apri il bot e
   Avvia → imposta i criteri → Attiva**.
3. Da lì riceve su Telegram solo le offerte sopra la **sua** soglia.

---

## Criteri di accettazione (checklist)

- [x] Un nuovo utente col solo link si registra, collega Gmail e Telegram e imposta
      i criteri, **senza** creare credenziali Google o bot propri.
- [x] Due utenti con criteri diversi ricevono notifiche diverse sullo stesso annuncio
      (verificato in `test_platform.py`).
- [x] Nessun segreto nel repository (`.env`, `data/`, credenziali → gitignored;
      token utenti cifrati Fernet nel DB).
- [x] Il ciclo parte ogni ora da GitHub Actions verso l'endpoint remoto.
- [x] La dashboard mostra stato connessioni, criteri, job con breakdown punteggio, log.
- [x] `companies.yaml` e `sources/company_scraper.py` restano nel repo, inutilizzati.

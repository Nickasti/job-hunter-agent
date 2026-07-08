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

### PASSO 3-5 — Deploy / cron ✅ COMPLETATO
- [x] App **LIVE su https://veredai.onrender.com** (Render free; migrata dal vecchio
      `job-hunter-platform.onrender.com`, poi eliminato — stesso DB Neon).
- [x] `PUBLIC_BASE_URL`, redirect URI Google, webhook Telegram, secret GitHub
      `RUN_CYCLE_URL`/`RUN_CYCLE_TOKEN` tutti allineati al dominio veredai.
- [x] Cron orario `job-hunter-cron` (curl → /api/run-cycle) operativo.
- [x] **Keepalive** `veredai-keepalive`: ping /healthz ogni 10 min (evita il cold start free tier).

### SICUREZZA ✅ (fatto)
- [x] Fix critico: `SESSION_SECRET` era rimasto al default pubblico → impostato forte su Render
      (verificato con test di cookie falsificato: ora RIFIUTATO). `TELEGRAM_WEBHOOK_SECRET` forte.
- [x] Cookie sessione `HttpOnly + Secure` in HTTPS.
- [x] Password bcrypt, token Google cifrati Fernet, segreti solo in env.
- [ ] (Opzionale) rate-limit login/registrazione.

### ADMIN ✅ (fatto)
- [x] Pagina **/admin** (visibile solo all'utente loggato con `ADMIN_EMAIL`, default
      niko.asti@gmail.com): elenco utenti, stato, Gmail/Telegram, **ultimo accesso**
      (`last_login_at` tracciato a ogni login), n. offerte/notificate. Link "Admin" in dashboard.

### RECUPERO PASSWORD ✅ (fatto)
- [x] `/forgot-password` → `/reset-password`: token monouso, scadenza 1h, anti-enumeration.
- [x] Invio email tramite **Brevo API** (HTTPS, gratis, no carta) — **SMTP diretto
      (Gmail) scartato**: verificato inaffidabile da Render free tier (porta 587
      bloccata/instabile, 0/5 invii riusciti nei test; Brevo 5/5 riusciti).
      Richiede `BREVO_API_KEY` + mittente verificato su Brevo.
- [x] Endpoint diagnostico `/api/test-email` (bearer) per verificare la config email.
- [x] Testato end-to-end in produzione: email ricevuta, link cliccato, password
      reimpostata con successo.

### PASSO 6 — Collaudo con utenti reali
- [ ] Aggiungere le email dei 2-3 tester come **Utenti di test** in Google Cloud
- [ ] Ogni tester: Registrati → Connetti Gmail → Avvia il bot Telegram → Criteri → Attiva
- [ ] Verificare che arrivino notifiche personalizzate e che la dashboard mostri i match
- [ ] Controllare un run reale: `Actions → job-hunter-cron → Run workflow` (o attendere il cron orario)

### PASSO 7 — Grafica / UI ✅ COMPLETATO (brand VeredAI)
- [x] **Rebranding VeredAI**: logo SVG (chevron su quadrato scuro + barra verde), nome,
      favicon, palette verde "del tragitto" (vedi memoria veredai-brand-palette).
- [x] **Onboarding/Home** (`/`): hero video a schermo intero, "Find Your Path / Find Your
      Job", claim bussola/meta, pulsante "Inizia ora". Landing pubblica per i non loggati.
- [x] **Setup** (`/onboarding/setup`): tema chiaro sage, accenti/checkbox verdi, bottoni brand.
- [x] **Dashboard** (`/dashboard`): tema chiaro verde, badge punteggio colorati, criteri, log.
- [x] **Login / Registrazione**: ridisegnate standalone, sfondo verde forest, card chiara.
- Font: Fustat (titoli), Schibsted Grotesk (logo/nav/bottoni), Inter (corpo).
- (Opzionale, non fatto) Video hero a risoluzione più alta o upscale AI (a crediti).

---

## 📌 Note operative
- Repo **pubblico** su GitHub (minuti Actions illimitati); nessun segreto committato.
- Render free "dorme" dopo inattività: il cron orario lo risveglia (curl con retry).
- Quota Gemini free condivisa tra utenti: gestita con budget/throttling/cache.
- Se si modifica il codice in locale: `git pull` prima di editare.
- Guida deploy dettagliata: [README_PLATFORM.md](README_PLATFORM.md).
- Server locale di prova: `uvicorn app.main:app --reload` → http://localhost:8000
  (usa sempre `localhost`, non `127.0.0.1`, per l'OAuth).

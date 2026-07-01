# 🎯 job-hunter-agent

Agente Python che monitora offerte di **stage curricolare a Lisbona** pertinenti al
profilo di Niccolò Asti (martech / data / AI marketing), le valuta con **Google
Gemini** e notifica i match su **Telegram**.

Due fonti:
1. **📧 Email LinkedIn Job Alerts** (via Gmail API)
2. **🌐 Web scraping** delle career page di 29 aziende target a Lisbona

Gira **gratis su GitHub Actions** (cron orario, modalità single-run). Nessun
servizio a pagamento, nessuna carta di credito richiesta.

---

## 📂 Struttura

```
job-hunter-agent/                  ← root del repository
├── main.py                        # entry point single-run
├── config.py                      # config da env / .env
├── models.py                      # dataclass Job + fingerprint dedup
├── companies.yaml                 # 29 aziende + strategia scraping
├── requirements.txt
├── .env.example
├── .gitignore
├── test_run.py                    # test end-to-end con mock (no rete)
├── sources/
│   ├── gmail_source.py            # fetch + parsing email LinkedIn
│   └── company_scraper.py         # scraping career page (api/static/dynamic)
├── scoring/
│   ├── gemini_scorer.py           # pre-filtro + Gemini + throttle/backoff
│   └── prompts.py                 # system prompt (logica Make)
├── notifier/
│   └── telegram.py                # invio messaggi MarkdownV2
├── storage/
│   ├── db.py                      # SQLite (dedup + cache score)
│   └── jobs.db                    # creato al primo run, committato dalla CI
├── tools/
│   ├── generate_gmail_token.py    # genera GMAIL_REFRESH_TOKEN (una volta)
│   └── get_telegram_chat_id.py    # trova il TELEGRAM_CHAT_ID
└── .github/workflows/run-agent.yml
```

---

## ✅ Prerequisiti

- **Python 3.11+** (solo per il setup locale dei token e i test)
- Un **account Google** (per Gmail API + Gemini)
- Un **bot Telegram**
- Un **repository GitHub** (consigliato **pubblico** — vedi nota minuti sotto)

---

## 🔧 Setup passo-passo

### 1. Clona / crea il repo

```bash
git clone <tuo-repo> job-hunter-agent
cd job-hunter-agent
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # per le career page JS-heavy
```

### 2. Gemini API key (gratis)

1. Vai su <https://aistudio.google.com/apikey>
2. **Create API key** → copia la chiave.
3. La metterai in `GEMINI_API_KEY`.

Free tier (indicativo): `gemini-2.5-flash-lite` ha limiti stretti (RPM/RPD). L'agente
li gestisce con throttling, backoff e cache (vedi *Gestione quota*).

### 3. Gmail API + refresh token (per CI/CD)

L'agente in CI **non usa file token**: ricostruisce le credenziali da
`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`. Il refresh token
si genera **una volta sola in locale**:

1. **Google Cloud Console** → crea/seleziona un progetto: <https://console.cloud.google.com/>
2. **APIs & Services → Library** → cerca **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External** → crea.
   - In **Test users** aggiungi il tuo indirizzo Gmail (`niko.asti@gmail.com`).
   - (Non serve pubblicare l'app: in modalità *Testing* il refresh token dura, basta
     restare tra i test users.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app** → crea → **Download JSON**.
   - Salva il file come `credentials.json` nella cartella del progetto.
5. Genera il refresh token:
   ```bash
   python tools/generate_gmail_token.py
   ```
   Si apre il browser → accedi → consenti. Lo script stampa:
   ```
   GMAIL_CLIENT_ID=...
   GMAIL_CLIENT_SECRET=...
   GMAIL_REFRESH_TOKEN=...
   ```
6. Conserva questi 3 valori (andranno nei GitHub Secrets). **Non committare**
   `credentials.json` (già in `.gitignore`).

> 💡 Lo scope richiesto è `gmail.readonly` (sola lettura).

### 4. Bot Telegram

1. Su Telegram apri **@BotFather** → `/newbot` → segui le istruzioni → copia il **token**.
2. Apri una chat **col tuo nuovo bot** e scrivigli `ciao`.
3. Ricava il chat id:
   ```bash
   python tools/get_telegram_chat_id.py <BOT_TOKEN>
   ```
   Copia `TELEGRAM_CHAT_ID`.

### 5. Test in locale

Crea `.env` da `.env.example` e compila i valori, poi:

```bash
# test end-to-end SENZA chiamare Gemini/Telegram reali:
python test_run.py

# run reale completo (legge Gmail, scrappa, scora, notifica):
python main.py
```

---

## ☁️ Deploy su GitHub Actions

### 1. Push del codice

La root del repo deve essere **questa cartella** (`main.py` e `.github/` in cima).

```bash
git init
git add .
git commit -m "init job-hunter-agent"
git branch -M main
git remote add origin <tuo-repo>
git push -u origin main
```

### 2. Configura i Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valore |
|---|---|
| `GEMINI_API_KEY` | la tua key di AI Studio |
| `GEMINI_MODEL` *(opz.)* | `gemini-2.5-flash-lite` |
| `TELEGRAM_BOT_TOKEN` | token di BotFather |
| `TELEGRAM_CHAT_ID` | il tuo chat id |
| `GMAIL_CLIENT_ID` | da generate_gmail_token.py |
| `GMAIL_CLIENT_SECRET` | da generate_gmail_token.py |
| `GMAIL_REFRESH_TOKEN` | da generate_gmail_token.py |

Opzionale, come **Variable** (non secret): `SCORE_THRESHOLD` (default 55).

### 3. Avvia

- **Actions → job-hunter-agent → Run workflow** per il primo run manuale.
- Poi parte da solo **ogni ora** (cron `0 * * * *`, orario UTC).

### ⚠️ Nota importante sui minuti Actions

Con Playwright + cron orario (~730 run/mese) un **repo privato** (2000 min/mese free)
può non bastare. Soluzioni gratuite:

- **Repo pubblico** → minuti Actions **illimitati**. I Secret restano cifrati e
  sicuri anche in repo pubblico; `jobs.db` contiene solo annunci pubblici.
- Oppure repo privato con cron meno frequente, es. ogni 2-3 ore:
  `cron: "0 */2 * * *"`.

> GitHub disabilita i workflow *scheduled* dopo ~60 giorni di inattività del repo.
> Il commit automatico di `jobs.db` ad ogni run tiene il repo "attivo".

---

## 🧠 Come funziona lo scoring

Replica la logica costruita su Make (max 100 punti):

| Criterio | Punti |
|---|---|
| **Lingua** | IT 25 · EN 20 · misto 25 · *solo PT → scarta* |
| **Contratto** | stage curricolare 30 · internship/trainee 25 · junior 15 · ambiguo 5 · *senior → scarta* |
| **Skills** | forte (3+) 25 · medio (1-2) 15 · debole 8 · off 0 |
| **Durata** | ≥6m 10 · 3-6m 8 · n/d 6 · *<3m → scarta* |
| **Retribuzione** | ≥1000€ 10 · 500-999€ 7 · <500€ 4 · n/d 6 |

**Soglia notifica Telegram: score ≥ 55** (configurabile via `SCORE_THRESHOLD`).

Prima di Gemini c'è un **pre-filtro locale** (keyword) che scarta i job palesemente
senior o totalmente fuori tema: risparmia quota senza chiamare il modello.

---

## ⚙️ Gestione quota Gemini

- **Throttling**: ≥ `GEMINI_MIN_INTERVAL` (default 4.5s) tra due chiamate.
- **Backoff esponenziale** sugli errori 429 / `RESOURCE_EXHAUSTED`.
- **Cache**: uno stesso job (stesso URL) già scorato negli ultimi
  `SCORE_CACHE_DAYS` (30) giorni riusa lo score salvato, niente nuova chiamata.
- **Budget per run**: `GEMINI_MAX_CALLS_PER_RUN` (default 80); superato il budget
  i job restanti **slittano al run successivo** (non vengono salvati, così
  verranno riprovati).

---

## 🏢 Tarare le aziende (`companies.yaml`)

Le voci con `verified: false` hanno URL/token **best-guess**: vanno confermati.

Per ogni azienda puoi impostare:

```yaml
- name: Talkdesk
  enabled: true
  strategy: api            # "api" | "static" | "dynamic"
  api_type: greenhouse     # solo per strategy=api ("greenhouse" | "lever")
  api_token: talkdesk      # board token dell'ATS
  career_page_url: "..."   # per static/dynamic
  selector: "a[href*='/job']"   # CSS selector delle card/anchor (opzionale)
  location_filter: ["Lisbon", "Lisboa", "Portugal"]
  keyword_filter: ["intern", "trainee", "junior", "estágio"]
```

**Come verificare un'azienda:**

1. **API (consigliata se disponibile)** — molte aziende usano Greenhouse o Lever:
   - Greenhouse: prova `https://boards-api.greenhouse.io/v1/boards/<token>/jobs`
     (il `<token>` è di solito il nome azienda nello slug della career page).
   - Lever: `https://api.lever.co/v0/postings/<token>?mode=json`.
   - Se l'endpoint risponde con JSON di job → imposta `strategy: api` e il `token`.
2. **static** — apri la career page; se gli annunci sono già nell'HTML (tasto
   destro → "Visualizza sorgente" e li trovi) → `strategy: static` + un `selector`
   che individui i link agli annunci.
3. **dynamic** — se gli annunci compaiono solo col JavaScript (SPA, Workday) →
   `strategy: dynamic` (usa Playwright). Imposta un `selector` su cui attendere.

Per aggiungere un'azienda: copia un blocco, cambia i campi, `enabled: true`.
Per disattivarla temporaneamente: `enabled: false`.

> Lo scraper rispetta sempre `robots.txt` e usa un rate limit conservativo.

---

## 🛠️ Troubleshooting

| Sintomo | Causa probabile / Fix |
|---|---|
| `Variabili mancanti: ...` | Secret/.env non impostati. Controlla i nomi esatti. |
| Nessuna email letta | Verifica i test users nell'OAuth consent screen e che gli alert LinkedIn arrivino davvero. Al primo run guarda solo `LINKEDIN_LOOKBACK_DAYS` giorni indietro. |
| `invalid_grant` su Gmail | Il refresh token è scaduto/revocato. Rigeneralo con `generate_gmail_token.py`. In modalità *Testing* resta valido finché sei tra i test users. |
| Gemini sempre 429 | Free tier saturo: abbassa la frequenza del cron, alza `GEMINI_MIN_INTERVAL`, o riduci le aziende `enabled`. |
| Telegram 400 *can't parse entities* | Carattere non escapato: già gestito da `escape_md`; se personalizzi il messaggio, ricordati l'escaping MarkdownV2. |
| Un'azienda dà 0 job | Config `verified: false` da tarare (vedi sopra) o pagina che richiede `dynamic`/login. |
| Playwright errore in CI | Lo step `playwright install --with-deps chromium` deve completare; controlla i log del job. |
| Notifiche duplicate | Significa che `jobs.db` non persiste: assicurati che lo step *Persist jobs.db* committi (permesso `contents: write`). |

---

## 📄 Note legali

- Scraping di `linkedin.com` **limitato alle pagine pubbliche** dei job
  (`/jobs/view/...`), **senza login**, con User-Agent realistico e rate limit
  conservativo (≥5s tra richieste). L'arricchimento è disattivabile con
  `ENABLE_LINKEDIN_ENRICH=false`.
- Scraping career page nel rispetto di `robots.txt`.
- Strumento per uso personale.
